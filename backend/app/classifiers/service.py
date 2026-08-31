from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.intelligence.classification_resolver import ClassificationDecision, resolve_classification
from app.intelligence.context_engine import build_context
from app.intelligence.radar import update_radar
from app.models import AIUsage, Classification, Tweet
from app.notifications.alert_manager import AlertManager
from app.schemas import ClassificationOutput, RuleClassification

from .providers import AIProvider, DeepSeekProvider, DeepSeekProviderError, ProviderResult, TranslationResult
from .rule_classifier import classify_rule


logger = logging.getLogger("radar.classification")


def provider_from_settings(settings: Settings) -> AIProvider | None:
    if not settings.deepseek_api_key:
        return None
    return DeepSeekProvider(
        api_key=settings.deepseek_api_key,
        model_name=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
    )


def persist_classification(
    session: Session,
    tweet_id: str,
    classifier_type: str,
    result: ClassificationOutput,
    *,
    model_name: str | None = None,
    prompt_version: str | None = None,
    classification_pending: bool = False,
    classification_conflict: bool = False,
) -> Classification:
    row = Classification(
        tweet_id=tweet_id,
        classifier_type=classifier_type,
        category=result.category,
        confidence=result.confidence,
        urgency=result.urgency,
        explicitness=result.explicitness,
        reason=result.reason,
        model_name=model_name,
        prompt_version=prompt_version,
        classification_pending=classification_pending,
        classification_conflict=classification_conflict,
    )
    session.add(row)
    session.flush()
    return row


def latest_final(session: Session, tweet_id: str) -> Classification | None:
    return session.scalar(
        select(Classification)
        .where(Classification.tweet_id == tweet_id, Classification.classifier_type == "final")
        .order_by(Classification.created_at.desc(), Classification.id.desc())
        .limit(1)
    )


def record_ai_usage(
    session: Session,
    provider: AIProvider,
    outcome: str,
    result: ProviderResult | TranslationResult | None = None,
    error: str | None = None,
) -> None:
    session.add(
        AIUsage(
            provider="deepseek",
            model_name=provider.model_name,
            outcome=outcome,
            input_tokens=result.input_tokens if result else None,
            output_tokens=result.output_tokens if result else None,
            error=error,
        )
    )


async def translate_tweet(
    session: Session,
    tweet_id: str,
    *,
    provider: AIProvider | None = None,
    settings: Settings | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Best-effort display translation; it never changes classification data."""

    settings = settings or get_settings()
    tweet = session.get(Tweet, tweet_id)
    if tweet is None:
        raise ValueError(f"Tweet not found: {tweet_id}")
    if not force and tweet.translated_zh and tweet.translation_version == settings.translation_version:
        return {"tweet_id": tweet_id, "translated": False, "skipped": True, "reason": "cached"}
    provider = provider or provider_from_settings(settings)
    translate = getattr(provider, "translate", None) if provider is not None else None
    if translate is None or not tweet.text.strip():
        return {"tweet_id": tweet_id, "translated": False, "skipped": True, "reason": "provider_unavailable"}
    try:
        result = await translate(tweet.text, context={"author": tweet.author, "is_reply": tweet.is_reply})
        tweet.translated_zh = result.translation_zh.strip()
        tweet.translation_model = provider.model_name
        tweet.translation_version = settings.translation_version
        tweet.translated_at = datetime.now(timezone.utc)
        record_ai_usage(
            session,
            provider,
            "translation_success",
            result,
        )
        session.flush()
        logger.info("TWEET_TRANSLATED tweet_id=%s", tweet_id)
        return {"tweet_id": tweet_id, "translated": True, "skipped": False}
    except Exception as exc:
        message = str(exc)[:300]
        if provider is not None:
            record_ai_usage(session, provider, "translation_failure", error=message)
        logger.warning("TWEET_TRANSLATION_FAILED tweet_id=%s reason=%s", tweet_id, message)
        return {"tweet_id": tweet_id, "translated": False, "skipped": False, "failed": True, "reason": message}


async def classify_tweet(
    session: Session,
    tweet_id: str,
    *,
    provider: AIProvider | None = None,
    settings: Settings | None = None,
    force: bool = False,
    mirror_event: Any | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    tweet = session.get(Tweet, tweet_id)
    if tweet is None:
        raise ValueError(f"Tweet not found: {tweet_id}")
    if not force and latest_final(session, tweet_id) is not None:
        return {"tweet_id": tweet_id, "skipped": True, "reason": "already_classified"}

    context = build_context(session, tweet)
    rule_result: RuleClassification = classify_rule(tweet.text, is_reply=tweet.is_reply)
    persist_classification(
        session,
        tweet_id,
        "rule",
        rule_result,
        prompt_version=settings.prompt_version,
    )
    logger.info("RULE_CLASSIFIED tweet_id=%s category=%s confidence=%.2f", tweet_id, rule_result.category, rule_result.confidence)

    ai_result: ClassificationOutput | None = None
    ai_pending = False
    ai_failed = False
    provider = provider or provider_from_settings(settings)
    if rule_result.requires_ai:
        logger.info("AI_CLASSIFICATION_REQUESTED tweet_id=%s", tweet_id)
        if provider is None:
            ai_pending = True
            ai_failed = True
            logger.warning("AI_CLASSIFICATION_FAILED tweet_id=%s reason=missing_api_key", tweet_id)
        else:
            try:
                provider_result = await provider.classify(context, rule_result)
                ai_result = provider_result.result
                record_ai_usage(session, provider, "success", provider_result)
                persist_classification(
                    session,
                    tweet_id,
                    "ai",
                    ai_result,
                    model_name=provider.model_name,
                    prompt_version=settings.prompt_version,
                )
                logger.info("AI_CLASSIFIED tweet_id=%s category=%s confidence=%.2f", tweet_id, ai_result.category, ai_result.confidence)
            except (DeepSeekProviderError, Exception) as exc:
                # The broad guard protects the collector from provider/library
                # failures while keeping the specific error in a safe log.
                ai_pending = True
                ai_failed = True
                message = str(exc)[:300]
                record_ai_usage(session, provider, "failure", error=message)
                logger.warning("AI_CLASSIFICATION_FAILED tweet_id=%s reason=%s", tweet_id, message)

    decision: ClassificationDecision = resolve_classification(rule_result, ai_result)
    if ai_failed:
        decision = ClassificationDecision(
            result=ClassificationOutput(
                category=decision.result.category,
                confidence=decision.result.confidence,
                urgency=decision.result.urgency,
                explicitness=decision.result.explicitness,
                reason=f"{decision.result.reason} AI unavailable; rule fallback retained.",
            ),
            conflict=decision.conflict,
            reason="ai_unavailable_fallback",
        )
    persist_classification(
        session,
        tweet_id,
        "final",
        decision.result,
        model_name=provider.model_name if provider and ai_result else None,
        prompt_version=settings.prompt_version,
        classification_pending=ai_pending,
        classification_conflict=decision.conflict,
    )
    # Translation is deliberately after the audited classification and is
    # isolated from it: a provider failure must not roll back intelligence.
    await translate_tweet(session, tweet_id, provider=provider, settings=settings)
    if decision.conflict:
        logger.warning("CLASSIFICATION_CONFLICT tweet_id=%s", tweet_id)
    logger.info("FINAL_CLASSIFICATION tweet_id=%s category=%s confidence=%.2f", tweet_id, decision.result.category, decision.result.confidence)
    radar = update_radar(session)
    AlertManager(settings).handle_radar_transition(session, radar)
    session.commit()
    if radar.changed:
        logger.info(
            "RADAR_STATE_CHANGED previous_state=%s state=%s trigger_tweet_id=%s",
            radar.previous_state,
            radar.state,
            radar.trigger_tweet_id,
        )
    if mirror_event is not None and (
        radar.changed
        or decision.result.category in {
            "reset_hint",
            "reset_announcement",
            "reset_in_progress",
            "reset_confirmed",
            "reset_denial",
            "quota_information",
        }
    ):
        mirror_event.set()
    return {
        "tweet_id": tweet_id,
        "skipped": False,
        "rule": rule_result.model_dump(),
        "ai": ai_result.model_dump() if ai_result else None,
        "final": decision.result.model_dump(),
        "classification_pending": ai_pending,
        "classification_conflict": decision.conflict,
        "radar_state": radar.state,
    }


async def translate_tweet_ids(
    session_factory,
    tweet_ids: list[str],
    *,
    force: bool = False,
    settings: Settings | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    provider = provider_from_settings(settings)
    counts = {"requested": len(tweet_ids), "translated": 0, "skipped": 0, "failed": 0}
    with session_factory() as session:
        for tweet_id in dict.fromkeys(tweet_ids):
            try:
                result = await translate_tweet(
                    session,
                    tweet_id,
                    provider=provider,
                    settings=settings,
                    force=force,
                )
                if result.get("translated"):
                    counts["translated"] += 1
                elif result.get("failed"):
                    counts["failed"] += 1
                else:
                    counts["skipped"] += 1
                session.commit()
            except Exception:
                session.rollback()
                counts["failed"] += 1
                logger.exception("Translation backfill failed tweet_id=%s", tweet_id)
    return counts


async def classify_tweet_ids(
    session_factory,
    tweet_ids: list[str],
    *,
    force: bool = False,
    settings: Settings | None = None,
    mirror_event: Any | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    provider = provider_from_settings(settings)
    counts = {"requested": len(tweet_ids), "classified": 0, "skipped": 0, "failed": 0}
    with session_factory() as session:
        for tweet_id in dict.fromkeys(tweet_ids):
            try:
                result = await classify_tweet(
                    session,
                    tweet_id,
                    provider=provider,
                    settings=settings,
                    force=force,
                    mirror_event=mirror_event,
                )
                counts["skipped" if result.get("skipped") else "classified"] += 1
            except Exception:
                session.rollback()
                counts["failed"] += 1
                logger.exception("Classification pipeline failed tweet_id=%s", tweet_id)
    return counts
