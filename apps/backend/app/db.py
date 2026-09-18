from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator

ACTION_LEVELS = {"GREEN", "YELLOW", "ORANGE", "RED", "UNKNOWN"}
LEVEL_ORDER = {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}
EVENT_TYPES = {"FULL_RESET", "SPECIAL_RESET"}
SPECIAL_TYPES = {"PARTIAL", "BANKED", "RESET_CARD", "STAGED", "EXTRA_CREDIT", "OTHER"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def normalise_time(value: str | datetime | None) -> str | None:
    if value is None or value == "":
        return None
    current = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat().replace("+00:00", "Z")


def content_hash(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode("utf-8")).hexdigest()


def text_language(text: str) -> str:
    letters = re.findall(r"[A-Za-z\u3400-\u9fff]", text)
    if not letters:
        return "unknown"
    return "zh" if len(re.findall(r"[\u3400-\u9fff]", text)) / len(letters) >= 0.25 else "en"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tibo_posts(
 id INTEGER PRIMARY KEY AUTOINCREMENT,tweet_id TEXT NOT NULL UNIQUE,posted_at TEXT,text TEXT NOT NULL,
 url TEXT NOT NULL,is_reply INTEGER NOT NULL DEFAULT 0,reply_to_tweet_id TEXT,collected_at TEXT NOT NULL,
 source TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reset_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT NOT NULL CHECK(event_type IN ('FULL_RESET','SPECIAL_RESET')),
 special_type TEXT CHECK(special_type IS NULL OR special_type IN ('PARTIAL','BANKED','RESET_CARD','STAGED','EXTRA_CREDIT','OTHER')),
 occurred_at TEXT NOT NULL,source_post_id INTEGER REFERENCES tibo_posts(id),title TEXT NOT NULL,summary TEXT NOT NULL,
 provenance TEXT NOT NULL,created_at TEXT NOT NULL,
 CHECK((event_type='FULL_RESET' AND special_type IS NULL) OR (event_type='SPECIAL_RESET' AND special_type IS NOT NULL)));
CREATE TABLE IF NOT EXISTS reset_cycles(
 id INTEGER PRIMARY KEY AUTOINCREMENT,started_at TEXT NOT NULL,ended_at TEXT,
 opened_by_reset_event_id INTEGER NOT NULL REFERENCES reset_events(id),closed_by_reset_event_id INTEGER REFERENCES reset_events(id),
 created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_reset_cycles_open ON reset_cycles((ended_at IS NULL)) WHERE ended_at IS NULL;
CREATE TABLE IF NOT EXISTS post_analysis(
 id INTEGER PRIMARY KEY AUTOINCREMENT,post_id INTEGER NOT NULL REFERENCES tibo_posts(id),analysis_type TEXT NOT NULL,
 model TEXT,prompt_version TEXT NOT NULL,category TEXT NOT NULL,evidence_json TEXT NOT NULL,summary TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS radar_judgements(
 id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,
 action_level TEXT NOT NULL CHECK(action_level IN ('GREEN','YELLOW','ORANGE','RED','UNKNOWN')),
 horizon_24h TEXT NOT NULL CHECK(horizon_24h IN ('GREEN','YELLOW','ORANGE','RED','UNKNOWN')),
 horizon_48h TEXT NOT NULL CHECK(horizon_48h IN ('GREEN','YELLOW','ORANGE','RED','UNKNOWN')),
 horizon_72h TEXT NOT NULL CHECK(horizon_72h IN ('GREEN','YELLOW','ORANGE','RED','UNKNOWN')),
 data_health TEXT NOT NULL,reason_summary TEXT NOT NULL,evidence_post_ids TEXT NOT NULL,special_event_ids TEXT NOT NULL,
 model TEXT,prompt_version TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_tibo_posts_posted_at ON tibo_posts(posted_at DESC);
CREATE INDEX IF NOT EXISTS ix_reset_events_occurred_at ON reset_events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_post_analysis_post_id ON post_analysis(post_id);
CREATE INDEX IF NOT EXISTS ix_radar_judgements_created_at ON radar_judgements(created_at DESC);
"""

V2_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS processing_jobs(
 id INTEGER PRIMARY KEY AUTOINCREMENT,job_type TEXT NOT NULL CHECK(job_type='POST_PROCESSING'),entity_key TEXT NOT NULL,
 payload_json TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','COMPLETED','FAILED')),
 attempts INTEGER NOT NULL DEFAULT 0,next_attempt_at TEXT,last_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 UNIQUE(job_type,entity_key));
CREATE TABLE IF NOT EXISTS reset_event_candidates(
 id INTEGER PRIMARY KEY AUTOINCREMENT,candidate_key TEXT NOT NULL UNIQUE,event_type TEXT NOT NULL,special_type TEXT,status TEXT NOT NULL,
 occurred_at_start TEXT,occurred_at_end TEXT,time_basis TEXT NOT NULL,scope TEXT NOT NULL,execution_stage TEXT NOT NULL,
 evidence_post_ids TEXT NOT NULL,summary TEXT NOT NULL,analysis_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline_state(key TEXT PRIMARY KEY,value_json TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS post_content_policies(
 post_id INTEGER NOT NULL REFERENCES tibo_posts(id) ON DELETE CASCADE,content_hash TEXT NOT NULL,
 policy_status TEXT NOT NULL,analysis_allowed INTEGER NOT NULL CHECK(analysis_allowed IN (0,1)),
 event_promotion_allowed INTEGER NOT NULL CHECK(event_promotion_allowed IN (0,1)),
 judge_evidence_allowed INTEGER NOT NULL CHECK(judge_evidence_allowed IN (0,1)),
 historical_case_allowed INTEGER NOT NULL CHECK(historical_case_allowed IN (0,1)),
 reason TEXT NOT NULL,decision_ids_json TEXT NOT NULL DEFAULT '[]',policy_version TEXT NOT NULL,
 applied_at TEXT NOT NULL,PRIMARY KEY(post_id,content_hash));
CREATE INDEX IF NOT EXISTS ix_processing_jobs_status ON processing_jobs(status,next_attempt_at,id);
CREATE INDEX IF NOT EXISTS ix_reset_candidates_status ON reset_event_candidates(status,updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_post_content_policies_post ON post_content_policies(post_id,content_hash);
"""

CORPUS_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS corpus_sources(
 source_id TEXT PRIMARY KEY,name TEXT NOT NULL,entry_url TEXT NOT NULL,accessed_at TEXT NOT NULL,
 access_status TEXT NOT NULL,acquisition_method TEXT NOT NULL,time_range_start TEXT,time_range_end TEXT,
 provides_tweet_ids INTEGER NOT NULL DEFAULT 0,reuse_status TEXT NOT NULL,content_kind TEXT NOT NULL,
 notes TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS historical_import_batches(
 batch_id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES corpus_sources(source_id),source_cutoff TEXT NOT NULL,
 started_at TEXT NOT NULL,completed_at TEXT,status TEXT NOT NULL,checkpoint_json TEXT NOT NULL DEFAULT '{}',
 statistics_json TEXT NOT NULL DEFAULT '{}',error TEXT,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS historical_import_changes(
 id INTEGER PRIMARY KEY AUTOINCREMENT,batch_id TEXT NOT NULL REFERENCES historical_import_batches(batch_id),
 source_id TEXT NOT NULL,source_record_key TEXT NOT NULL,tweet_id TEXT NOT NULL,post_id INTEGER,
 change_type TEXT NOT NULL,before_post_json TEXT,before_evidence_json TEXT,after_post_updated_at TEXT,
 created_at TEXT NOT NULL,rolled_back_at TEXT,UNIQUE(batch_id,source_id,source_record_key));
CREATE TABLE IF NOT EXISTS post_source_evidence(
 id INTEGER PRIMARY KEY AUTOINCREMENT,post_id INTEGER REFERENCES tibo_posts(id),source_id TEXT NOT NULL REFERENCES corpus_sources(source_id),
 source_record_key TEXT NOT NULL,evidence_url TEXT NOT NULL,captured_at TEXT NOT NULL,content_kind TEXT NOT NULL,
 text_snapshot TEXT,content_hash TEXT,posted_at_claim TEXT,time_source TEXT NOT NULL,time_precision TEXT NOT NULL,
 verification_status TEXT NOT NULL,completeness_status TEXT NOT NULL,is_truncated INTEGER NOT NULL DEFAULT 0,
 has_context INTEGER NOT NULL DEFAULT 0,conflict_status TEXT NOT NULL DEFAULT 'none',source_label TEXT NOT NULL DEFAULT '',
 metadata_json TEXT NOT NULL DEFAULT '{}',batch_id TEXT REFERENCES historical_import_batches(batch_id),updated_at TEXT NOT NULL,
 UNIQUE(source_id,source_record_key));
CREATE TABLE IF NOT EXISTS historical_cases(
 case_id TEXT PRIMARY KEY,post_id INTEGER REFERENCES tibo_posts(id),source_id TEXT NOT NULL REFERENCES corpus_sources(source_id),
 source_record_key TEXT NOT NULL,posted_at TEXT NOT NULL,original_text TEXT NOT NULL,context_text TEXT NOT NULL DEFAULT '',
 outcome_type TEXT NOT NULL,outcome_at TEXT,outcome_time_precision TEXT NOT NULL,verification_status TEXT NOT NULL,
 coverage_limitations TEXT NOT NULL DEFAULT '',pattern_tags_json TEXT NOT NULL DEFAULT '[]',related_tweet_ids_json TEXT NOT NULL DEFAULT '[]',
 corpus_version TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS corpus_coverage(
 id INTEGER PRIMARY KEY AUTOINCREMENT,source_id TEXT NOT NULL REFERENCES corpus_sources(source_id),period_start TEXT NOT NULL,
 period_end TEXT NOT NULL,acquired_posts INTEGER NOT NULL DEFAULT 0,reset_candidates INTEGER NOT NULL DEFAULT 0,
 verified_events INTEGER NOT NULL DEFAULT 0,coverage_status TEXT NOT NULL,known_gaps TEXT NOT NULL DEFAULT '',
 batch_id TEXT REFERENCES historical_import_batches(batch_id),updated_at TEXT NOT NULL,
 UNIQUE(source_id,period_start,period_end));
CREATE TABLE IF NOT EXISTS historical_event_dispositions(
 id INTEGER PRIMARY KEY AUTOINCREMENT,disposition_key TEXT NOT NULL UNIQUE,
 source_id TEXT NOT NULL REFERENCES corpus_sources(source_id),source_record_key TEXT NOT NULL,
 tweet_id TEXT,source_claimed_status TEXT NOT NULL DEFAULT '',local_verification_status TEXT NOT NULL,
 disposition TEXT NOT NULL,event_id INTEGER REFERENCES reset_events(id),candidate_id INTEGER REFERENCES reset_event_candidates(id),
 related_tweet_ids_json TEXT NOT NULL DEFAULT '[]',reason TEXT NOT NULL,missing_evidence TEXT NOT NULL DEFAULT '',
 metadata_json TEXT NOT NULL DEFAULT '{}',batch_id TEXT REFERENCES historical_import_batches(batch_id),
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_evidence_post_id ON post_source_evidence(post_id);
CREATE INDEX IF NOT EXISTS ix_evidence_source ON post_source_evidence(source_id,source_record_key);
CREATE INDEX IF NOT EXISTS ix_historical_cases_posted_at ON historical_cases(active,posted_at DESC);
CREATE INDEX IF NOT EXISTS ix_corpus_coverage_period ON corpus_coverage(period_start,period_end);
CREATE INDEX IF NOT EXISTS ix_historical_changes_batch ON historical_import_changes(batch_id,id);
CREATE INDEX IF NOT EXISTS ix_historical_dispositions_source ON historical_event_dispositions(source_id,source_record_key);
CREATE INDEX IF NOT EXISTS ix_historical_dispositions_status ON historical_event_dispositions(disposition,updated_at DESC);
"""

POST_COLUMNS = {
    "original_text": "TEXT", "original_language": "TEXT NOT NULL DEFAULT 'unknown'",
    "original_text_source": "TEXT NOT NULL DEFAULT 'legacy_or_collector'", "translated_text": "TEXT",
    "text_hash": "TEXT", "analysis_status": "TEXT NOT NULL DEFAULT 'PENDING'",
    "translation_status": "TEXT NOT NULL DEFAULT 'PENDING'", "processing_error": "TEXT",
    "last_seen_at": "TEXT", "updated_at": "TEXT",
    "ingestion_mode": "TEXT NOT NULL DEFAULT 'realtime'", "import_batch_id": "TEXT",
    "source_cutoff": "TEXT", "content_completeness": "TEXT NOT NULL DEFAULT 'unknown'",
    "verification_status": "TEXT NOT NULL DEFAULT 'unverified'", "context_status": "TEXT NOT NULL DEFAULT 'unknown'",
    "conflict_status": "TEXT NOT NULL DEFAULT 'none'", "time_source": "TEXT NOT NULL DEFAULT 'collector'",
    "time_precision": "TEXT NOT NULL DEFAULT 'unknown'",
}
ANALYSIS_COLUMNS = {
    "content_hash": "TEXT", "analysis_json": "TEXT NOT NULL DEFAULT '{}'",
    "status": "TEXT NOT NULL DEFAULT 'COMPLETED'", "error": "TEXT", "updated_at": "TEXT",
}
EVENT_COLUMNS = {
    "event_key": "TEXT", "occurred_at_end": "TEXT", "time_basis": "TEXT NOT NULL DEFAULT 'reported_event_time'",
    "scope": "TEXT NOT NULL DEFAULT 'unknown'", "execution_stage": "TEXT NOT NULL DEFAULT 'unknown'",
    "evidence_post_ids": "TEXT NOT NULL DEFAULT '[]'", "updated_at": "TEXT",
}
JUDGEMENT_COLUMNS = {
    "estimated_start": "TEXT", "estimated_end": "TEXT", "estimate_basis": "TEXT", "valid_until": "TEXT",
    "cycle_id": "INTEGER", "status": "TEXT NOT NULL DEFAULT 'COMPLETED'", "failure_reason": "TEXT",
    "context_hash": "TEXT", "raw_json": "TEXT NOT NULL DEFAULT '{}'", "corpus_version": "TEXT",
    "historical_case_ids": "TEXT NOT NULL DEFAULT '[]'",
}
EVIDENCE_COLUMNS = {
    "source_claimed_status": "TEXT NOT NULL DEFAULT ''",
    "local_verification_status": "TEXT NOT NULL DEFAULT 'not_independently_verified'",
    "author_handle": "TEXT",
    "source_time_raw": "TEXT",
    "source_timezone": "TEXT",
    "time_semantics": "TEXT NOT NULL DEFAULT 'unknown'",
    "parent_tweet_id": "TEXT",
    "upstream_record_key": "TEXT",
}


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _add_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, declaration in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    def initialize(self) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA_SQL)
            self._add_columns(connection, "tibo_posts", POST_COLUMNS)
            self._add_columns(connection, "post_analysis", ANALYSIS_COLUMNS)
            self._add_columns(connection, "reset_events", EVENT_COLUMNS)
            self._add_columns(connection, "radar_judgements", JUDGEMENT_COLUMNS)
            connection.executescript(V2_TABLES_SQL)
            connection.executescript(CORPUS_TABLES_SQL)
            self._add_columns(connection, "post_source_evidence", EVIDENCE_COLUMNS)
            connection.execute(
                """UPDATE post_source_evidence SET source_claimed_status=verification_status
                WHERE source_claimed_status=''"""
            )
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_post_analysis_version ON post_analysis(post_id,analysis_type,content_hash,prompt_version,model)")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_reset_events_key ON reset_events(event_key) WHERE event_key IS NOT NULL")
            for row in connection.execute("SELECT id,text,original_text,original_language,text_hash,collected_at,created_at FROM tibo_posts").fetchall():
                original = str(row["original_text"] or row["text"] or "")
                language = row["original_language"] if row["original_language"] != "unknown" else text_language(original)
                connection.execute(
                    "UPDATE tibo_posts SET original_text=?,original_language=?,text_hash=?,last_seen_at=COALESCE(last_seen_at,?),updated_at=COALESCE(updated_at,?) WHERE id=?",
                    (original, language, row["text_hash"] or content_hash(original), row["collected_at"], row["created_at"] or now, row["id"]),
                )
            self._consolidate_event_keys(connection)
            connection.execute("INSERT OR IGNORE INTO schema_versions VALUES(1,?)", (now,))
            connection.execute("INSERT OR IGNORE INTO schema_versions VALUES(2,?)", (now,))
            connection.execute("INSERT OR IGNORE INTO schema_versions VALUES(3,?)", (now,))
            connection.execute("INSERT OR IGNORE INTO schema_versions VALUES(4,?)", (now,))
            connection.execute("INSERT OR IGNORE INTO schema_versions VALUES(5,?)", (now,))
            connection.execute("INSERT OR IGNORE INTO schema_versions VALUES(6,?)", (now,))

    def counts(self) -> dict[str, int]:
        with self.connect() as connection:
            return {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in (
                "tibo_posts", "reset_events", "reset_event_candidates", "post_analysis", "radar_judgements", "processing_jobs",
                "post_content_policies", "post_source_evidence", "historical_cases", "historical_import_batches",
                "historical_event_dispositions")}

    def upsert_content_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        """Attach use restrictions to one immutable content version.

        Policies are deliberately keyed by both the post and its content hash. A
        later corrected capture does not inherit an obsolete restriction, but it
        stays quarantined until that new version receives an explicit policy.
        Posts that have never had a policy keep the normal realtime defaults.
        """
        tweet_id = str(policy["tweet_id"])
        expected_hash = str(policy["content_hash"])
        fields = (
            "analysis_allowed",
            "event_promotion_allowed",
            "judge_evidence_allowed",
            "historical_case_allowed",
        )
        if any(not isinstance(policy.get(field), bool) for field in fields):
            raise ValueError("content policy use flags must be booleans")
        decision_ids = [str(item) for item in policy.get("decision_ids") or []]
        with self.connect() as connection:
            post = connection.execute(
                "SELECT id,text_hash FROM tibo_posts WHERE tweet_id=?", (tweet_id,)
            ).fetchone()
            if post is None:
                raise ValueError(f"unknown content-policy tweet ID: {tweet_id}")
            connection.execute(
                """INSERT INTO post_content_policies(
                post_id,content_hash,policy_status,analysis_allowed,event_promotion_allowed,
                judge_evidence_allowed,historical_case_allowed,reason,decision_ids_json,policy_version,applied_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(post_id,content_hash) DO UPDATE SET
                policy_status=excluded.policy_status,analysis_allowed=excluded.analysis_allowed,
                event_promotion_allowed=excluded.event_promotion_allowed,
                judge_evidence_allowed=excluded.judge_evidence_allowed,
                historical_case_allowed=excluded.historical_case_allowed,reason=excluded.reason,
                decision_ids_json=excluded.decision_ids_json,policy_version=excluded.policy_version,
                applied_at=excluded.applied_at""",
                (
                    post["id"], expected_hash, str(policy.get("policy_status") or "RESTRICTED"),
                    *(1 if policy[field] else 0 for field in fields),
                    str(policy.get("reason") or "reviewed content-use policy"),
                    json.dumps(decision_ids, ensure_ascii=False),
                    str(policy.get("policy_version") or "content-policy-v1"), utc_now(),
                ),
            )
        return {
            "tweet_id": tweet_id,
            "content_hash": expected_hash,
            "current_content_hash": str(post["text_hash"]),
            "applies_to_current_content": expected_hash == str(post["text_hash"]),
        }

    def content_policy(self, post_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            post = connection.execute("SELECT text_hash FROM tibo_posts WHERE id=?", (post_id,)).fetchone()
            if post is None:
                return None
            exact = connection.execute(
                "SELECT * FROM post_content_policies WHERE post_id=? AND content_hash=?",
                (post_id, post["text_hash"]),
            ).fetchone()
            if exact is not None:
                result = dict(exact)
                result["decision_ids"] = json.loads(result.pop("decision_ids_json") or "[]")
                for field in (
                    "analysis_allowed", "event_promotion_allowed", "judge_evidence_allowed",
                    "historical_case_allowed",
                ):
                    result[field] = bool(result[field])
                result["content_version_matches"] = True
                return result
            history = connection.execute(
                "SELECT 1 FROM post_content_policies WHERE post_id=? LIMIT 1", (post_id,)
            ).fetchone()
        if history is None:
            return None
        return {
            "post_id": post_id,
            "content_hash": str(post["text_hash"]),
            "policy_status": "CONTENT_VERSION_CHANGED_REVIEW_REQUIRED",
            "analysis_allowed": False,
            "event_promotion_allowed": False,
            "judge_evidence_allowed": False,
            "historical_case_allowed": False,
            "reason": "content changed after a reviewed restriction; re-analysis is required",
            "decision_ids": [],
            "policy_version": "content-policy-v1",
            "content_version_matches": False,
        }

    def content_use_allowed(self, post: dict[str, Any], use: str) -> bool:
        field = {
            "analysis": "analysis_allowed",
            "event_promotion": "event_promotion_allowed",
            "judge_evidence": "judge_evidence_allowed",
            "historical_case": "historical_case_allowed",
        }.get(use)
        if field is None:
            raise ValueError(f"unknown content use: {use}")
        policy = self.content_policy(int(post["id"]))
        return policy is None or bool(policy[field])

    def restricted_tweet_ids(self, use: str) -> set[str]:
        column = {
            "analysis": "analysis_allowed",
            "event_promotion": "event_promotion_allowed",
            "judge_evidence": "judge_evidence_allowed",
            "historical_case": "historical_case_allowed",
        }.get(use)
        if column is None:
            raise ValueError(f"unknown content use: {use}")
        with self.connect() as connection:
            rows = connection.execute(
                f"""SELECT p.tweet_id FROM tibo_posts p
                WHERE EXISTS(SELECT 1 FROM post_content_policies any_policy WHERE any_policy.post_id=p.id)
                AND NOT EXISTS(SELECT 1 FROM post_content_policies exact_policy
                    WHERE exact_policy.post_id=p.id AND exact_policy.content_hash=p.text_hash
                    AND exact_policy.{column}=1)"""
            ).fetchall()
        return {str(row["tweet_id"]) for row in rows}

    def mark_post_input_restricted(self, post_id: int, reason: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """UPDATE tibo_posts SET analysis_status='INPUT_RESTRICTED',processing_error=?,updated_at=?
                WHERE id=?""",
                (reason[:1000], utc_now(), post_id),
            )

    def upsert_posts_detailed(self, posts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        now = utc_now()
        with self.connect() as connection:
            for post in posts:
                tweet_id = str(post["tweet_id"])
                incoming = str(post.get("text") or "").strip()
                incoming_language, incoming_hash = text_language(incoming), content_hash(incoming)
                row = connection.execute("SELECT * FROM tibo_posts WHERE tweet_id=?", (tweet_id,)).fetchone()
                if row is None:
                    cursor = connection.execute(
                        """INSERT INTO tibo_posts(
                        tweet_id,posted_at,text,url,is_reply,reply_to_tweet_id,collected_at,source,created_at,
                        original_text,original_language,original_text_source,translated_text,text_hash,analysis_status,
                        translation_status,last_seen_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (tweet_id, normalise_time(post.get("posted_at")), incoming,
                         str(post.get("url") or f"https://x.com/thsottiaux/status/{tweet_id}"), 1 if post.get("is_reply") else 0,
                         post.get("reply_to_tweet_id"), normalise_time(post.get("collected_at")) or now,
                         str(post.get("source") or "collector_adapter"), now, incoming, incoming_language, "collector_capture",
                         incoming if incoming_language == "zh" else None, incoming_hash, "PENDING",
                         "COMPLETED" if incoming_language == "zh" else "PENDING", now, now),
                    )
                    results.append({"tweet_id": tweet_id, "post_id": int(cursor.lastrowid), "status": "new", "content_hash": incoming_hash, "queue": True})
                    continue

                original = str(row["original_text"] or row["text"] or "")
                language = str(row["original_language"] or text_language(original))
                old_hash = str(row["text_hash"] or content_hash(original))
                translated, status, queue = row["translated_text"], "duplicate", False
                if incoming and incoming_hash != old_hash:
                    if language == "en" and incoming_language == "zh":
                        translated, status = incoming, "updated"
                    elif language == "zh" and incoming_language == "en":
                        translated, original, language, old_hash, status, queue = translated or original, incoming, "en", incoming_hash, "updated", True
                    elif incoming_language != "unknown":
                        original, language, old_hash, status, queue = incoming, incoming_language, incoming_hash, "updated", True
                connection.execute(
                    """UPDATE tibo_posts SET posted_at=COALESCE(?,posted_at),text=?,original_text=?,original_language=?,
                    original_text_source='collector_capture',translated_text=?,text_hash=?,url=?,is_reply=?,
                    reply_to_tweet_id=COALESCE(?,reply_to_tweet_id),last_seen_at=?,updated_at=?,
                    source=CASE WHEN ?!='duplicate' THEN ? ELSE source END,
                    collected_at=CASE WHEN ?!='duplicate' THEN ? ELSE collected_at END,
                    analysis_status=CASE WHEN ? THEN 'PENDING' ELSE analysis_status END,
                    translation_status=CASE WHEN ? THEN CASE WHEN ?='zh' THEN 'COMPLETED' ELSE 'PENDING' END ELSE translation_status END,
                    processing_error=CASE WHEN ? THEN NULL ELSE processing_error END WHERE id=?""",
                    (normalise_time(post.get("posted_at")), original, original, language, translated, old_hash,
                     str(post.get("url") or row["url"]), 1 if post.get("is_reply") else 0, post.get("reply_to_tweet_id"), now, now,
                     status, str(post.get("source") or "collector_adapter"), status, normalise_time(post.get("collected_at")) or now,
                     queue, queue, language, queue, row["id"]),
                )
                results.append({"tweet_id": tweet_id, "post_id": int(row["id"]), "status": status, "content_hash": old_hash, "queue": queue})
        return results

    def upsert_posts(self, posts: Iterable[dict[str, Any]]) -> int:
        return sum(item["status"] != "duplicate" for item in self.upsert_posts_detailed(posts))

    def register_corpus_source(self, source: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO corpus_sources(source_id,name,entry_url,accessed_at,access_status,acquisition_method,
                time_range_start,time_range_end,provides_tweet_ids,reuse_status,content_kind,notes,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
                name=excluded.name,entry_url=excluded.entry_url,accessed_at=excluded.accessed_at,
                access_status=excluded.access_status,acquisition_method=excluded.acquisition_method,
                time_range_start=excluded.time_range_start,time_range_end=excluded.time_range_end,
                provides_tweet_ids=excluded.provides_tweet_ids,reuse_status=excluded.reuse_status,
                content_kind=excluded.content_kind,notes=excluded.notes,updated_at=excluded.updated_at""",
                (
                    source["source_id"], source["name"], source["entry_url"],
                    normalise_time(source.get("accessed_at")) or now, source.get("access_status", "accessible"),
                    source.get("acquisition_method", "public_http"), normalise_time(source.get("time_range_start")),
                    normalise_time(source.get("time_range_end")), 1 if source.get("provides_tweet_ids") else 0,
                    source.get("reuse_status", "not_explicitly_granted"), source.get("content_kind", "third_party_index"),
                    source.get("notes", ""), now,
                ),
            )

    def begin_historical_batch(self, batch_id: str, source_id: str, source_cutoff: str, *, checkpoint: dict[str, Any] | None = None) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO historical_import_batches(batch_id,source_id,source_cutoff,started_at,status,
                checkpoint_json,statistics_json,updated_at) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(batch_id) DO UPDATE SET status='RUNNING',checkpoint_json=excluded.checkpoint_json,
                error=NULL,updated_at=excluded.updated_at""",
                (batch_id, source_id, normalise_time(source_cutoff), now, "RUNNING",
                 json.dumps(checkpoint or {}, ensure_ascii=False), "{}", now),
            )

    def finish_historical_batch(
        self,
        batch_id: str,
        *,
        status: str,
        statistics: dict[str, Any],
        checkpoint: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """UPDATE historical_import_batches SET completed_at=?,status=?,checkpoint_json=?,statistics_json=?,
                error=?,updated_at=? WHERE batch_id=?""",
                (now if status in {"COMPLETED", "FAILED", "PARTIAL"} else None, status,
                 json.dumps(checkpoint or {}, ensure_ascii=False), json.dumps(statistics, ensure_ascii=False),
                 error[:1000] if error else None, now, batch_id),
            )

    def rollback_historical_batch(self, batch_id: str) -> dict[str, int]:
        """Conservatively undo only this batch, never clearing unrelated corpus data."""
        statistics = {"evidence_restored": 0, "evidence_removed": 0, "posts_restored": 0,
                      "posts_removed": 0, "posts_skipped_newer_change": 0, "coverage_removed": 0}
        now = utc_now()
        with self.connect() as connection:
            batch = connection.execute("SELECT status FROM historical_import_batches WHERE batch_id=?", (batch_id,)).fetchone()
            if batch is None:
                raise ValueError(f"unknown historical batch: {batch_id}")
            changes = connection.execute(
                "SELECT * FROM historical_import_changes WHERE batch_id=? AND rolled_back_at IS NULL ORDER BY id DESC",
                (batch_id,),
            ).fetchall()
            for change in changes:
                before_evidence = json.loads(change["before_evidence_json"]) if change["before_evidence_json"] else None
                current_evidence = connection.execute(
                    "SELECT * FROM post_source_evidence WHERE source_id=? AND source_record_key=?",
                    (change["source_id"], change["source_record_key"]),
                ).fetchone()
                if before_evidence is not None:
                    if current_evidence is not None and current_evidence["batch_id"] == batch_id:
                        connection.execute("DELETE FROM post_source_evidence WHERE id=?", (current_evidence["id"],))
                        columns = list(before_evidence)
                        placeholders = ",".join("?" for _ in columns)
                        connection.execute(
                            f"INSERT INTO post_source_evidence({','.join(columns)}) VALUES({placeholders})",
                            [before_evidence[column] for column in columns],
                        )
                        statistics["evidence_restored"] += 1
                elif current_evidence is not None and current_evidence["batch_id"] == batch_id:
                    connection.execute("DELETE FROM post_source_evidence WHERE id=?", (current_evidence["id"],))
                    statistics["evidence_removed"] += 1

                current_post = connection.execute("SELECT * FROM tibo_posts WHERE id=?", (change["post_id"],)).fetchone()
                before_post = json.loads(change["before_post_json"]) if change["before_post_json"] else None
                if current_post is not None and current_post["updated_at"] == change["after_post_updated_at"]:
                    if before_post is None:
                        other_evidence = connection.execute(
                            "SELECT COUNT(*) FROM post_source_evidence WHERE post_id=?", (change["post_id"],)
                        ).fetchone()[0]
                        if not other_evidence and current_post["ingestion_mode"] == "historical" and current_post["import_batch_id"] == batch_id:
                            connection.execute("UPDATE historical_cases SET post_id=NULL,updated_at=? WHERE post_id=?", (now, change["post_id"]))
                            connection.execute("DELETE FROM tibo_posts WHERE id=?", (change["post_id"],))
                            statistics["posts_removed"] += 1
                    else:
                        columns = [column for column in before_post if column != "id"]
                        assignments = ",".join(f"{column}=?" for column in columns)
                        connection.execute(
                            f"UPDATE tibo_posts SET {assignments} WHERE id=?",
                            [before_post[column] for column in columns] + [change["post_id"]],
                        )
                        statistics["posts_restored"] += 1
                elif current_post is not None:
                    statistics["posts_skipped_newer_change"] += 1
                connection.execute("UPDATE historical_import_changes SET rolled_back_at=? WHERE id=?", (now, change["id"]))
            statistics["coverage_removed"] = connection.execute(
                "DELETE FROM corpus_coverage WHERE batch_id=?", (batch_id,)
            ).rowcount
            connection.execute(
                "UPDATE historical_import_batches SET status='ROLLED_BACK',statistics_json=?,updated_at=? WHERE batch_id=?",
                (json.dumps(statistics), now, batch_id),
            )
        return statistics

    @staticmethod
    def _verification_rank(value: str) -> int:
        return {
            "unverified": 0,
            "not_independently_verified": 1,
            "indexed_only": 1,
            "source_quoted": 2,
            "cross_source_correlated": 3,
            "direct_verified": 3,
            "direct_original_verified": 4,
        }.get(value, 0)

    def upsert_historical_record(
        self,
        record: dict[str, Any],
        *,
        source_id: str,
        batch_id: str,
        source_cutoff: str,
    ) -> dict[str, Any]:
        tweet_id = str(record["tweet_id"])
        incoming = str(record.get("text") or "").strip()
        if not incoming:
            raise ValueError(f"historical record {tweet_id} has no text")
        posted_at = normalise_time(record.get("posted_at"))
        if posted_at is None:
            raise ValueError(f"historical record {tweet_id} has no posted_at")
        captured_at = normalise_time(record.get("captured_at")) or utc_now()
        incoming_language = text_language(incoming)
        incoming_hash = content_hash(incoming)
        verification = str(record.get("verification_status") or "unverified")
        local_verification = str(record.get("local_verification_status") or "not_independently_verified")
        effective_verification = (
            local_verification
            if local_verification in {"cross_source_correlated", "direct_original_verified"}
            else verification
        )
        now = utc_now()
        status = "duplicate"
        conflict = "none"
        enriched = False
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tibo_posts WHERE tweet_id=?", (tweet_id,)).fetchone()
            before_post = dict(row) if row is not None else None
            previous_evidence = connection.execute(
                "SELECT * FROM post_source_evidence WHERE source_id=? AND source_record_key=?",
                (source_id, str(record["source_record_key"])),
            ).fetchone()
            before_evidence = dict(previous_evidence) if previous_evidence is not None else None
            if row is None:
                cursor = connection.execute(
                    """INSERT INTO tibo_posts(
                    tweet_id,posted_at,text,url,is_reply,reply_to_tweet_id,collected_at,source,created_at,
                    original_text,original_language,original_text_source,translated_text,text_hash,analysis_status,
                    translation_status,last_seen_at,updated_at,ingestion_mode,import_batch_id,source_cutoff,
                    content_completeness,verification_status,context_status,conflict_status,time_source,time_precision)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        tweet_id, posted_at, incoming, record.get("url") or f"https://x.com/thsottiaux/status/{tweet_id}",
                        1 if record.get("is_reply") else 0, record.get("reply_to_tweet_id"), captured_at,
                        f"historical:{source_id}", now, incoming, incoming_language,
                        record.get("content_kind", "third_party_quote"), None, incoming_hash,
                        "HISTORICAL_UNANALYSED", "NOT_REQUESTED", captured_at, now, "historical", batch_id,
                        normalise_time(source_cutoff), record.get("completeness_status", "unknown"), effective_verification,
                        record.get("context_status", "unknown"), "none", record.get("time_source", "source_claim"),
                        record.get("time_precision", "unknown"),
                    ),
                )
                post_id = int(cursor.lastrowid)
                status = "new"
            else:
                post_id = int(row["id"])
                existing = str(row["original_text"] or row["text"] or "")
                existing_hash = str(row["text_hash"] or content_hash(existing))
                existing_language = str(row["original_language"] or text_language(existing))
                if existing_hash != incoming_hash:
                    trusted_english = incoming_language == "en" and effective_verification in {
                        "cross_source_correlated", "direct_original_verified", "direct_verified"
                    }
                    historical_upgrade = (
                        row["ingestion_mode"] == "historical"
                        and self._verification_rank(effective_verification) > self._verification_rank(str(row["verification_status"]))
                    )
                    if trusted_english and (existing_language == "zh" or historical_upgrade):
                        translation_fallback = existing if existing_language == "zh" else row["translated_text"]
                        connection.execute(
                            """UPDATE tibo_posts SET text=?,original_text=?,original_language='en',
                            original_text_source=?,translated_text=COALESCE(translated_text,?),text_hash=?,
                            analysis_status='HISTORICAL_UNANALYSED',translation_status=CASE WHEN translated_text IS NULL
                            AND ? IS NOT NULL THEN 'COMPLETED' ELSE translation_status END,content_completeness=?,verification_status=?,
                            context_status=?,time_source=?,time_precision=?,conflict_status='resolved_prefer_direct_original',
                            updated_at=? WHERE id=?""",
                            (incoming, incoming, record.get("content_kind", "direct_original"), translation_fallback, incoming_hash,
                             translation_fallback,
                             record.get("completeness_status", "unknown"), effective_verification,
                             record.get("context_status", "unknown"), record.get("time_source", "source_claim"),
                             record.get("time_precision", "unknown"), now, post_id),
                        )
                        status, conflict, enriched = "enriched", "resolved_prefer_direct_original", True
                    else:
                        status, conflict = "conflict", "text_mismatch_preserved"
                        connection.execute("UPDATE tibo_posts SET conflict_status=?,updated_at=? WHERE id=?", (conflict, now, post_id))
                elif self._verification_rank(effective_verification) > self._verification_rank(str(row["verification_status"])):
                    connection.execute(
                        """UPDATE tibo_posts SET verification_status=?,content_completeness=?,context_status=?,
                        time_source=?,time_precision=?,updated_at=? WHERE id=?""",
                        (effective_verification, record.get("completeness_status", row["content_completeness"]),
                         record.get("context_status", row["context_status"]), record.get("time_source", row["time_source"]),
                         record.get("time_precision", row["time_precision"]), now, post_id),
                    )
                    status, enriched = "enriched", True
                connection.execute(
                    "UPDATE tibo_posts SET last_seen_at=MAX(COALESCE(last_seen_at,''),?),updated_at=? WHERE id=?",
                    (captured_at, now, post_id),
                )

            connection.execute(
                """INSERT INTO post_source_evidence(post_id,source_id,source_record_key,evidence_url,captured_at,
                content_kind,text_snapshot,content_hash,posted_at_claim,time_source,time_precision,verification_status,
                completeness_status,is_truncated,has_context,conflict_status,source_label,metadata_json,batch_id,updated_at,
                source_claimed_status,local_verification_status,author_handle,source_time_raw,source_timezone,time_semantics,
                parent_tweet_id,upstream_record_key)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id,source_record_key) DO UPDATE SET
                post_id=excluded.post_id,evidence_url=excluded.evidence_url,captured_at=excluded.captured_at,
                content_kind=excluded.content_kind,text_snapshot=excluded.text_snapshot,content_hash=excluded.content_hash,
                posted_at_claim=excluded.posted_at_claim,time_source=excluded.time_source,time_precision=excluded.time_precision,
                verification_status=excluded.verification_status,completeness_status=excluded.completeness_status,
                is_truncated=excluded.is_truncated,has_context=excluded.has_context,conflict_status=excluded.conflict_status,
                source_label=excluded.source_label,metadata_json=excluded.metadata_json,batch_id=excluded.batch_id,
                updated_at=excluded.updated_at,source_claimed_status=excluded.source_claimed_status,
                local_verification_status=excluded.local_verification_status,author_handle=excluded.author_handle,
                source_time_raw=excluded.source_time_raw,source_timezone=excluded.source_timezone,
                time_semantics=excluded.time_semantics,parent_tweet_id=excluded.parent_tweet_id,
                upstream_record_key=excluded.upstream_record_key""",
                (
                    post_id, source_id, str(record["source_record_key"]), record.get("evidence_url") or record.get("url") or "",
                    captured_at, record.get("content_kind", "third_party_quote"), incoming, incoming_hash, posted_at,
                    record.get("time_source", "source_claim"), record.get("time_precision", "unknown"), verification,
                    record.get("completeness_status", "unknown"), 1 if record.get("is_truncated") else 0,
                    1 if record.get("has_context") else 0, conflict, record.get("source_label", ""),
                    json.dumps(record.get("metadata") or {}, ensure_ascii=False), batch_id, now,
                    str(record.get("source_claimed_status") or verification),
                    str(record.get("local_verification_status") or "not_independently_verified"),
                    record.get("author_handle"), record.get("source_time_raw"), record.get("source_timezone"),
                    record.get("time_semantics", "unknown"), record.get("parent_tweet_id"),
                    record.get("upstream_record_key"),
                ),
            )
            after_row = connection.execute("SELECT updated_at FROM tibo_posts WHERE id=?", (post_id,)).fetchone()
            connection.execute(
                """INSERT INTO historical_import_changes(batch_id,source_id,source_record_key,tweet_id,post_id,
                change_type,before_post_json,before_evidence_json,after_post_updated_at,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(batch_id,source_id,source_record_key) DO UPDATE SET
                post_id=excluded.post_id,change_type=excluded.change_type,
                after_post_updated_at=excluded.after_post_updated_at""",
                (batch_id, source_id, str(record["source_record_key"]), tweet_id, post_id, status,
                 json.dumps(before_post, ensure_ascii=False) if before_post is not None else None,
                 json.dumps(before_evidence, ensure_ascii=False) if before_evidence is not None else None,
                 after_row["updated_at"] if after_row else None, now),
            )
        return {"tweet_id": tweet_id, "post_id": post_id, "status": status, "conflict": conflict, "enriched": enriched}

    def upsert_historical_case(self, case: dict[str, Any]) -> None:
        now = utc_now()
        with self.connect() as connection:
            post = connection.execute("SELECT id FROM tibo_posts WHERE tweet_id=?", (str(case["tweet_id"]),)).fetchone()
            connection.execute(
                """INSERT INTO historical_cases(case_id,post_id,source_id,source_record_key,posted_at,original_text,
                context_text,outcome_type,outcome_at,outcome_time_precision,verification_status,coverage_limitations,
                pattern_tags_json,related_tweet_ids_json,corpus_version,active,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET
                post_id=excluded.post_id,source_id=excluded.source_id,source_record_key=excluded.source_record_key,
                posted_at=excluded.posted_at,original_text=excluded.original_text,context_text=excluded.context_text,
                outcome_type=excluded.outcome_type,outcome_at=excluded.outcome_at,
                outcome_time_precision=excluded.outcome_time_precision,verification_status=excluded.verification_status,
                coverage_limitations=excluded.coverage_limitations,pattern_tags_json=excluded.pattern_tags_json,
                related_tweet_ids_json=excluded.related_tweet_ids_json,corpus_version=excluded.corpus_version,
                active=excluded.active,updated_at=excluded.updated_at""",
                (
                    case["case_id"], int(post["id"]) if post else None, case["source_id"], case["source_record_key"],
                    normalise_time(case["posted_at"]), case["original_text"], case.get("context_text", ""),
                    case["outcome_type"], normalise_time(case.get("outcome_at")),
                    case.get("outcome_time_precision", "unknown"), case.get("verification_status", "unverified"),
                    case.get("coverage_limitations", ""), json.dumps(case.get("pattern_tags") or []),
                    json.dumps(case.get("related_tweet_ids") or []), case["corpus_version"],
                    1 if case.get("active", True) else 0, now, now,
                ),
            )

    def upsert_historical_disposition(self, item: dict[str, Any]) -> int:
        """Persist one source claim's local disposition without promoting it implicitly."""
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO historical_event_dispositions(
                disposition_key,source_id,source_record_key,tweet_id,source_claimed_status,
                local_verification_status,disposition,event_id,candidate_id,related_tweet_ids_json,
                reason,missing_evidence,metadata_json,batch_id,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(disposition_key) DO UPDATE SET
                source_id=excluded.source_id,source_record_key=excluded.source_record_key,
                tweet_id=excluded.tweet_id,source_claimed_status=excluded.source_claimed_status,
                local_verification_status=excluded.local_verification_status,disposition=excluded.disposition,
                event_id=excluded.event_id,candidate_id=excluded.candidate_id,
                related_tweet_ids_json=excluded.related_tweet_ids_json,reason=excluded.reason,
                missing_evidence=excluded.missing_evidence,metadata_json=excluded.metadata_json,
                batch_id=excluded.batch_id,updated_at=excluded.updated_at""",
                (
                    item["disposition_key"], item["source_id"], item["source_record_key"],
                    str(item["tweet_id"]) if item.get("tweet_id") else None,
                    str(item.get("source_claimed_status") or ""),
                    str(item.get("local_verification_status") or "not_independently_verified"),
                    item["disposition"], item.get("event_id"), item.get("candidate_id"),
                    json.dumps([str(value) for value in item.get("related_tweet_ids") or []]),
                    item["reason"], item.get("missing_evidence", ""),
                    json.dumps(item.get("metadata") or {}, ensure_ascii=False), item.get("batch_id"), now, now,
                ),
            )
            row = connection.execute(
                "SELECT id FROM historical_event_dispositions WHERE disposition_key=?",
                (item["disposition_key"],),
            ).fetchone()
        return int(row["id"])

    def list_historical_dispositions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM historical_event_dispositions ORDER BY source_id,source_record_key,disposition_key"
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["related_tweet_ids"] = json.loads(item.pop("related_tweet_ids_json") or "[]")
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            results.append(item)
        return results

    def upsert_corpus_coverage(self, item: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO corpus_coverage(source_id,period_start,period_end,acquired_posts,reset_candidates,
                verified_events,coverage_status,known_gaps,batch_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_id,period_start,period_end) DO UPDATE SET acquired_posts=excluded.acquired_posts,
                reset_candidates=excluded.reset_candidates,verified_events=excluded.verified_events,
                coverage_status=excluded.coverage_status,known_gaps=excluded.known_gaps,batch_id=excluded.batch_id,
                updated_at=excluded.updated_at""",
                (item["source_id"], normalise_time(item["period_start"]), normalise_time(item["period_end"]),
                 int(item.get("acquired_posts", 0)), int(item.get("reset_candidates", 0)),
                 int(item.get("verified_events", 0)), item["coverage_status"], item.get("known_gaps", ""),
                 item.get("batch_id"), utc_now()),
            )

    def delete_corpus_coverage_for_batch(self, batch_id: str) -> None:
        """Remove only coverage summaries owned by one idempotently rerun import batch."""
        with self.connect() as connection:
            connection.execute("DELETE FROM corpus_coverage WHERE batch_id=?", (batch_id,))

    def corpus_version(self) -> str | None:
        state = self.get_state("corpus", {})
        return str(state.get("version")) if state.get("version") else None

    def retrieve_historical_cases(
        self,
        posts: list[dict[str, Any]],
        *,
        limit: int = 6,
        as_of: str | datetime | None = None,
    ) -> list[dict[str, Any]]:
        cutoff = normalise_time(as_of) if as_of else None
        with self.connect() as connection:
            if cutoff:
                rows = connection.execute(
                    """SELECT * FROM historical_cases WHERE active=1 AND posted_at<=?
                    AND (outcome_at IS NULL OR outcome_at<=?) ORDER BY posted_at DESC""",
                    (cutoff, cutoff),
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM historical_cases WHERE active=1 ORDER BY posted_at DESC").fetchall()
        current_post_ids = {int(post["id"]) for post in posts if post.get("id") is not None}
        restricted_tweet_ids = self.restricted_tweet_ids("historical_case")
        corpus_text = " ".join(str(post.get("original_text") or post.get("text") or "").lower() for post in posts)
        keyword_tags = {
            "banked": ("banked", "reset card"), "explicit_future": ("will", "landing", "next hour", "tomorrow"),
            "completed": ("propagated", "have reset", "all reset", "brand new usage"),
            "teaser": ("signs", "hold on", "dashboard", "milestone", "button"),
            "celebration": ("celebrate", "users", "weekend", "enjoy"),
            "incident": ("issue", "outage", "fix", "consumed", "reliability"),
            "delay_or_condition": ("moved", "delay", "if", "by end of day"),
            "product_discussion": ("feature", "model", "roadmap", "remove"),
            "negative_or_delay": ("not a reset", "but no", "delayed", "moved"),
            "dual_effect": ("banked", "another one", "twice", "full reset"),
            "completion_evidence": ("have reset", "has been reset", "propagated", "it is done"),
        }
        current_tags = {tag for tag, words in keyword_tags.items() if any(word in corpus_text for word in words)}
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            item = dict(row)
            if item.get("post_id") is not None and int(item["post_id"]) in current_post_ids:
                continue
            item["pattern_tags"] = json.loads(item.pop("pattern_tags_json") or "[]")
            item["related_tweet_ids"] = json.loads(item.pop("related_tweet_ids_json") or "[]")
            if item.get("post_id") is not None:
                linked_post = self.get_post(int(item["post_id"]))
                if linked_post and not self.content_use_allowed(linked_post, "historical_case"):
                    continue
            if restricted_tweet_ids.intersection(str(value) for value in item["related_tweet_ids"]):
                continue
            overlap = len(current_tags.intersection(item["pattern_tags"]))
            score = overlap * 10 + self._verification_rank(item["verification_status"])
            scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], pair[1]["posted_at"]), reverse=True)
        selected: list[dict[str, Any]] = []
        outcome_counts: dict[str, int] = {}
        for _, item in scored:
            outcome = str(item["outcome_type"])
            if outcome_counts.get(outcome, 0) >= 2:
                continue
            selected.append(item)
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
            if len(selected) >= max(1, min(limit, 10)):
                break
        return selected

    def corpus_inventory(self) -> dict[str, Any]:
        with self.connect() as connection:
            scalar = lambda query: int(connection.execute(query).fetchone()[0])
            return {
                "version": self.corpus_version(),
                "sources": scalar("SELECT COUNT(*) FROM corpus_sources"),
                "batches": scalar("SELECT COUNT(*) FROM historical_import_batches"),
                "evidence": scalar("SELECT COUNT(*) FROM post_source_evidence"),
                "cases": scalar("SELECT COUNT(*) FROM historical_cases WHERE active=1"),
                "conflicts": scalar("SELECT COUNT(*) FROM post_source_evidence WHERE conflict_status!='none'"),
                "direct_verified": scalar("SELECT COUNT(*) FROM post_source_evidence WHERE verification_status='direct_verified'"),
                "source_quoted": scalar("SELECT COUNT(*) FROM post_source_evidence WHERE verification_status='source_quoted'"),
                "dispositions": scalar("SELECT COUNT(*) FROM historical_event_dispositions"),
                "unresolved_dispositions": scalar(
                    "SELECT COUNT(*) FROM historical_event_dispositions WHERE disposition IN "
                    "('NEEDS_ORIGINAL','NEEDS_CONTEXT','SCOPE_OR_TIME_UNCLEAR','FUTURE_ANNOUNCEMENT')"
                ),
            }

    def get_post(self, post_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tibo_posts WHERE id=?", (post_id,)).fetchone()
        return self._post(row) if row else None

    def get_post_by_tweet_id(self, tweet_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tibo_posts WHERE tweet_id=?", (tweet_id,)).fetchone()
        return self._post(row) if row else None

    def latest_analysis(self, post_id: int, post_hash: str, prompt_version: str, model: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT analysis_json FROM post_analysis WHERE post_id=? AND analysis_type='post_semantics'
                AND content_hash=? AND prompt_version=? AND model=? AND status='COMPLETED' ORDER BY id DESC LIMIT 1""",
                (post_id, post_hash, prompt_version, model),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list_posts(self, limit: int = 20, *, as_of: str | datetime | None = None) -> list[dict[str, Any]]:
        cutoff = normalise_time(as_of) if as_of else None
        with self.connect() as connection:
            where = "WHERE COALESCE(p.posted_at,p.collected_at)<=?" if cutoff else ""
            params: tuple[Any, ...] = (cutoff, max(1, min(limit, 100))) if cutoff else (max(1, min(limit, 100)),)
            rows = connection.execute(f"""
                SELECT p.*,
                (SELECT a.analysis_json FROM post_analysis a WHERE a.post_id=p.id AND a.analysis_type='post_semantics' AND a.status='COMPLETED' ORDER BY a.id DESC LIMIT 1) latest_analysis_json
                FROM tibo_posts p {where} ORDER BY COALESCE(p.posted_at,p.collected_at) DESC,p.id DESC LIMIT ?""",
                params).fetchall()
        return [self._post(row) for row in rows]

    def bootstrap_posts(self, candidate_ids: list[str], recent_limit: int = 12, hours: int = 72) -> list[dict[str, Any]]:
        cutoff = normalise_time(datetime.now(UTC) - timedelta(hours=hours))
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM tibo_posts WHERE ingestion_mode!='historical' AND posted_at>=? ORDER BY posted_at DESC LIMIT 40", (cutoff,)).fetchall()
            rows += connection.execute("SELECT * FROM tibo_posts WHERE ingestion_mode!='historical' ORDER BY COALESCE(posted_at,collected_at) DESC LIMIT ?", (recent_limit,)).fetchall()
            if candidate_ids:
                placeholders = ",".join("?" for _ in candidate_ids)
                rows += connection.execute(f"SELECT * FROM tibo_posts WHERE ingestion_mode!='historical' AND tweet_id IN ({placeholders})", candidate_ids).fetchall()
        return list({int(row["id"]): self._post(row) for row in rows}.values())

    def enqueue_post(self, post_id: int, identity: str) -> bool:
        now = utc_now()
        with self.connect() as connection:
            existing = connection.execute("SELECT status FROM processing_jobs WHERE job_type='POST_PROCESSING' AND entity_key=?", (identity,)).fetchone()
            connection.execute("""INSERT INTO processing_jobs(job_type,entity_key,payload_json,status,attempts,created_at,updated_at)
                VALUES('POST_PROCESSING',?,?,'PENDING',0,?,?) ON CONFLICT(job_type,entity_key) DO UPDATE SET
                status=CASE WHEN processing_jobs.status='FAILED' THEN 'PENDING' ELSE processing_jobs.status END,
                next_attempt_at=CASE WHEN processing_jobs.status='FAILED' THEN NULL ELSE processing_jobs.next_attempt_at END,
                last_error=CASE WHEN processing_jobs.status='FAILED' THEN NULL ELSE processing_jobs.last_error END,updated_at=excluded.updated_at""",
                (identity, json.dumps({"post_id": post_id}), now, now))
        return existing is None or existing["status"] == "FAILED"

    def recover_jobs(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("UPDATE processing_jobs SET status='PENDING',next_attempt_at=NULL,updated_at=? WHERE status='RUNNING'", (utc_now(),)).rowcount)

    def claim_post_job(self) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("""SELECT * FROM processing_jobs WHERE job_type='POST_PROCESSING' AND status='PENDING'
                AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY id LIMIT 1""", (now,)).fetchone()
            if not row:
                return None
            connection.execute("UPDATE processing_jobs SET status='RUNNING',attempts=attempts+1,updated_at=? WHERE id=?", (now, row["id"]))
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        result["attempts"] = int(result["attempts"]) + 1
        return result

    def finish_job(self, job_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE processing_jobs SET status='COMPLETED',last_error=NULL,next_attempt_at=NULL,updated_at=? WHERE id=?", (utc_now(), job_id))

    def fail_job(self, job_id: int, error: str, retry_at: str | None) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE processing_jobs SET status=?,last_error=?,next_attempt_at=?,updated_at=? WHERE id=?",
                               ("PENDING" if retry_at else "FAILED", error[:1000], retry_at, utc_now(), job_id))

    def pending_job_count(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM processing_jobs WHERE status IN ('PENDING','RUNNING')").fetchone()[0])

    def save_analysis(self, post_id: int, post_hash: str, model: str, prompt_version: str, analysis: dict[str, Any]) -> int:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("""INSERT INTO post_analysis(post_id,analysis_type,model,prompt_version,category,evidence_json,summary,
                created_at,content_hash,analysis_json,status,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(post_id,analysis_type,content_hash,prompt_version,model) DO UPDATE SET category=excluded.category,
                evidence_json=excluded.evidence_json,summary=excluded.summary,analysis_json=excluded.analysis_json,status='COMPLETED',error=NULL,updated_at=excluded.updated_at""",
                (post_id, "post_semantics", model, prompt_version, str(analysis.get("category") or "other"),
                 json.dumps({"quote": analysis.get("evidence_quote"), "tweet_id": analysis.get("tweet_id")}, ensure_ascii=False),
                 str(analysis.get("summary") or ""), now, post_hash, json.dumps(analysis, ensure_ascii=False), "COMPLETED", now))
            row = connection.execute("SELECT id FROM post_analysis WHERE post_id=? AND analysis_type='post_semantics' AND content_hash=? AND prompt_version=? AND model=?",
                                     (post_id, post_hash, prompt_version, model)).fetchone()
            connection.execute("UPDATE tibo_posts SET analysis_status='COMPLETED',processing_error=NULL,updated_at=? WHERE id=? AND text_hash=?", (now, post_id, post_hash))
        return int(row["id"])

    def save_translation(self, post_id: int, post_hash: str, translation: str | None, error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute("""UPDATE tibo_posts SET translated_text=COALESCE(?,translated_text),translation_status=?,
                processing_error=CASE WHEN ? IS NULL THEN processing_error ELSE ? END,updated_at=? WHERE id=? AND text_hash=?""",
                (translation, "COMPLETED" if translation else "FAILED", error, error[:1000] if error else None, utc_now(), post_id, post_hash))

    def mark_post_failure(self, post_id: int, error: str) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE tibo_posts SET analysis_status='FAILED',processing_error=?,updated_at=? WHERE id=?", (error[:1000], utc_now(), post_id))

    def upsert_candidate(self, candidate: dict[str, Any]) -> int:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("""INSERT INTO reset_event_candidates(candidate_key,event_type,special_type,status,occurred_at_start,
                occurred_at_end,time_basis,scope,execution_stage,evidence_post_ids,summary,analysis_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(candidate_key) DO UPDATE SET event_type=excluded.event_type,
                special_type=excluded.special_type,status=excluded.status,occurred_at_start=excluded.occurred_at_start,
                occurred_at_end=excluded.occurred_at_end,time_basis=excluded.time_basis,scope=excluded.scope,
                execution_stage=excluded.execution_stage,evidence_post_ids=excluded.evidence_post_ids,summary=excluded.summary,
                analysis_json=excluded.analysis_json,updated_at=excluded.updated_at""",
                (candidate["candidate_key"], candidate["event_type"], candidate.get("special_type"), candidate.get("status", "NEEDS_REVIEW"),
                 normalise_time(candidate.get("occurred_at_start")), normalise_time(candidate.get("occurred_at_end")),
                 candidate.get("time_basis", "unknown"), candidate.get("scope", "unknown"), candidate.get("execution_stage", "unknown"),
                 json.dumps(candidate.get("evidence_post_ids") or []), candidate.get("summary", ""),
                 json.dumps(candidate.get("analysis") or {}, ensure_ascii=False), now, now))
            row = connection.execute("SELECT id FROM reset_event_candidates WHERE candidate_key=?", (candidate["candidate_key"],)).fetchone()
        return int(row["id"])

    def upsert_reset_event(self, event: dict[str, Any]) -> dict[str, Any]:
        event_type = str(event["event_type"]).upper()
        special_type = str(event.get("special_type") or "").upper() or None
        if event_type not in EVENT_TYPES or (event_type == "FULL_RESET" and special_type) or (event_type == "SPECIAL_RESET" and special_type not in SPECIAL_TYPES):
            raise ValueError("invalid reset event type")
        occurred_at = normalise_time(event["occurred_at"])
        evidence = sorted({str(item) for item in event.get("evidence_post_ids") or []})
        event_key = str(event.get("event_key") or self.canonical_event_key(event_type, special_type, occurred_at, evidence))
        now = utc_now()
        with self.connect() as connection:
            existing = connection.execute("SELECT * FROM reset_events WHERE event_key=?", (event_key,)).fetchone()
            if existing is None and not event.get("event_key"):
                # Compatibility with already assigned legacy keys. A reviewed
                # event can already carry a time range and the later evidence
                # post. Reprocessing that post must reuse the reviewed event,
                # but proximity or time alone must never merge independent
                # events. Require both shared evidence and overlapping ranges.
                matches = connection.execute(
                    "SELECT * FROM reset_events WHERE event_type=? AND special_type IS ?",
                    (event_type, special_type),
                ).fetchall()
                incoming_end = normalise_time(event.get("occurred_at_end")) or occurred_at
                compatible = []
                for row in matches:
                    row_evidence = set(json.loads(row["evidence_post_ids"] or "[]"))
                    row_end = row["occurred_at_end"] or row["occurred_at"]
                    ranges_overlap = occurred_at <= row_end and row["occurred_at"] <= incoming_end
                    if (row_evidence & set(evidence) and ranges_overlap) or (
                        not evidence and not row_evidence and row["occurred_at"] == occurred_at
                        and row["source_post_id"] == event.get("source_post_id")
                    ):
                        compatible.append(row)
                if len(compatible) == 1:
                    existing = compatible[0]
                elif len(compatible) > 1:
                    raise ValueError("reset evidence overlaps multiple existing events")
            if existing:
                if existing["event_type"] != event_type or existing["special_type"] != special_type:
                    raise ValueError("explicit event key cannot change event mechanism")
                evidence = sorted(set(json.loads(existing["evidence_post_ids"] or "[]")) | set(evidence))
                range_start = min(existing["occurred_at"], occurred_at)
                range_end = max(existing["occurred_at_end"] or existing["occurred_at"], normalise_time(event.get("occurred_at_end")) or occurred_at)
                connection.execute("""UPDATE reset_events SET occurred_at=?,occurred_at_end=?,source_post_id=COALESCE(source_post_id,?),
                    title=?,summary=?,provenance=?,time_basis=?,scope=?,execution_stage=?,evidence_post_ids=?,updated_at=? WHERE id=?""",
                    (range_start, range_end, event.get("source_post_id"), event["title"], event["summary"],
                     json.dumps(event.get("provenance") or {}, ensure_ascii=False), event.get("time_basis", "reported_event_time"),
                     event.get("scope", "unknown"), event.get("execution_stage", "unknown"), json.dumps(evidence), now, existing["id"]))
                event_id = int(existing["id"])
            else:
                cursor = connection.execute("""INSERT INTO reset_events(event_type,special_type,occurred_at,source_post_id,title,summary,
                    provenance,created_at,event_key,occurred_at_end,time_basis,scope,execution_stage,evidence_post_ids,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (event_type, special_type, occurred_at, event.get("source_post_id"), event["title"], event["summary"],
                     json.dumps(event.get("provenance") or {}, ensure_ascii=False), now, event_key,
                     normalise_time(event.get("occurred_at_end")), event.get("time_basis", "reported_event_time"),
                     event.get("scope", "unknown"), event.get("execution_stage", "unknown"), json.dumps(evidence), now))
                event_id = int(cursor.lastrowid)
            self._rebuild_cycles(connection)
            row = connection.execute("SELECT * FROM reset_events WHERE id=?", (event_id,)).fetchone()
        return self._event(row)

    def record_reset_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return self.upsert_reset_event(event)

    @staticmethod
    def _rebuild_cycles(connection: sqlite3.Connection) -> None:
        events = connection.execute("SELECT id,occurred_at,created_at FROM reset_events WHERE event_type='FULL_RESET' ORDER BY occurred_at,id").fetchall()
        existing = {row["opened_by_reset_event_id"]: row["id"] for row in connection.execute("SELECT id,opened_by_reset_event_id FROM reset_cycles")}
        # Close the old open row before opening the new one, inside the same
        # transaction. Preserve cycle IDs referenced by earlier judgements.
        connection.execute("UPDATE reset_cycles SET ended_at=started_at WHERE ended_at IS NULL")
        for index, event in enumerate(events):
            following = events[index + 1] if index + 1 < len(events) else None
            if event["id"] in existing:
                connection.execute("UPDATE reset_cycles SET started_at=?,ended_at=?,closed_by_reset_event_id=? WHERE id=?",
                    (event["occurred_at"], following["occurred_at"] if following else None,
                     following["id"] if following else None, existing[event["id"]]))
            else:
                connection.execute("INSERT INTO reset_cycles(started_at,ended_at,opened_by_reset_event_id,closed_by_reset_event_id,created_at) VALUES(?,?,?,?,?)",
                    (event["occurred_at"], following["occurred_at"] if following else None, event["id"], following["id"] if following else None, event["created_at"]))

    @staticmethod
    def canonical_event_key(event_type: str, special_type: str | None, occurred_at: str, evidence_post_ids: Iterable[str] = ()) -> str:
        identity = [event_type, special_type, normalise_time(occurred_at), sorted(set(evidence_post_ids))]
        return content_hash(json.dumps(identity, separators=(",", ":")))[:32]

    @classmethod
    def _consolidate_event_keys(cls, connection: sqlite3.Connection) -> None:
        # Initialization is not semantic adjudication: do not delete or merge
        # historical events merely because their times fall in one six-hour bin.
        rows = connection.execute("SELECT id FROM reset_events WHERE event_key IS NULL OR event_key=''").fetchall()
        for row in rows:
            connection.execute("UPDATE reset_events SET event_key=? WHERE id=?",
                               (f"legacy-event-{row['id']}", row["id"]))
        cls._rebuild_cycles(connection)

    def list_reset_events(self, limit: int = 50, *, as_of: str | datetime | None = None) -> list[dict[str, Any]]:
        cutoff = normalise_time(as_of) if as_of else None
        with self.connect() as connection:
            if cutoff:
                rows = connection.execute(
                    "SELECT * FROM reset_events WHERE occurred_at<=? ORDER BY occurred_at DESC,id DESC LIMIT ?",
                    (cutoff, max(1, min(limit, 200))),
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM reset_events ORDER BY occurred_at DESC,id DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return [self._event(row) for row in rows]

    def list_candidates(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM reset_event_candidates ORDER BY updated_at DESC,id DESC LIMIT ?", (limit,)).fetchall()
        results = []
        for row in rows:
            item = dict(row); item["evidence_post_ids"] = json.loads(item["evidence_post_ids"]); item["analysis"] = json.loads(item.pop("analysis_json")); results.append(item)
        return results

    def last_full_reset(self, *, as_of: str | datetime | None = None) -> dict[str, Any] | None:
        cutoff = normalise_time(as_of) if as_of else None
        with self.connect() as connection:
            if cutoff:
                row = connection.execute(
                    "SELECT * FROM reset_events WHERE event_type='FULL_RESET' AND occurred_at<=? ORDER BY occurred_at DESC,id DESC LIMIT 1",
                    (cutoff,),
                ).fetchone()
            else:
                row = connection.execute("SELECT * FROM reset_events WHERE event_type='FULL_RESET' ORDER BY occurred_at DESC,id DESC LIMIT 1").fetchone()
        return self._event(row) if row else None

    def cycles(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM reset_cycles ORDER BY started_at,id").fetchall()]

    def current_cycle(self, *, as_of: str | datetime | None = None) -> dict[str, Any] | None:
        cutoff = normalise_time(as_of) if as_of else None
        with self.connect() as connection:
            if cutoff:
                row = connection.execute(
                    """SELECT * FROM reset_cycles WHERE started_at<=? AND (ended_at IS NULL OR ended_at>?)
                    ORDER BY started_at DESC LIMIT 1""",
                    (cutoff, cutoff),
                ).fetchone()
            else:
                row = connection.execute("SELECT * FROM reset_cycles WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def judgement_context(self, post_limit: int = 24, *, as_of: str | datetime | None = None) -> dict[str, Any]:
        candidates = self.list_posts(min(100, max(post_limit * 4, post_limit)), as_of=as_of)
        source_posts = [
            post for post in candidates
            if post.get("analysis") and self.content_use_allowed(post, "judge_evidence")
        ][:post_limit]
        posts = [{"tweet_id": p["tweet_id"], "posted_at": p["posted_at"], "text": p["original_text"],
                  "is_reply": p["is_reply"], "analysis": p.get("analysis")}
                 for p in source_posts]
        restricted = self.restricted_tweet_ids("judge_evidence")
        eligible_events: list[dict[str, Any]] = []
        for event in self.list_reset_events(200, as_of=as_of):
            original_evidence = [str(item) for item in event.get("evidence_post_ids") or []]
            eligible_evidence = [item for item in original_evidence if item not in restricted]
            if original_evidence and not eligible_evidence:
                continue
            current = dict(event)
            current["evidence_post_ids"] = eligible_evidence
            eligible_events.append(current)
        reset_events = eligible_events[:12]
        last_full_reset = next((event for event in eligible_events if event["event_type"] == "FULL_RESET"), None)
        current_cycle = None
        if last_full_reset is not None:
            with self.connect() as connection:
                row = connection.execute(
                    "SELECT * FROM reset_cycles WHERE opened_by_reset_event_id=?",
                    (last_full_reset["id"],),
                ).fetchone()
            if row is not None:
                current_cycle = dict(row)
                current_cycle["ended_at"] = None
                current_cycle["closed_by_reset_event_id"] = None
        previous_judgement = self.latest_judgement(as_of=as_of)
        if previous_judgement and not self.judgement_is_usable(previous_judgement, at=as_of):
            previous_judgement = None
        return {"posts": posts, "reset_events": reset_events,
                "last_full_reset": last_full_reset,
                "current_cycle": current_cycle,
                "previous_judgement": previous_judgement,
                "corpus_version": self.corpus_version(),
                "historical_cases": self.retrieve_historical_cases(source_posts, as_of=as_of)}

    def add_judgement(self, judgement: dict[str, Any]) -> int:
        values = [str(judgement[key]).upper() for key in ("action_level", "horizon_24h", "horizon_48h", "horizon_72h")]
        if any(value not in ACTION_LEVELS for value in values):
            raise ValueError("invalid action or horizon level")
        horizon_order = [LEVEL_ORDER.get(value) for value in values[1:]]
        if all(value is not None for value in horizon_order) and not (horizon_order[0] <= horizon_order[1] <= horizon_order[2]):
            raise ValueError("horizon levels must be cumulative: 24h <= 48h <= 72h")
        evidence = [str(item) for item in judgement.get("evidence_post_ids") or []]
        if evidence:
            with self.connect() as connection:
                placeholders = ",".join("?" for _ in evidence)
                found = {str(row[0]) for row in connection.execute(f"SELECT tweet_id FROM tibo_posts WHERE tweet_id IN ({placeholders})", evidence)}
            missing = sorted(set(evidence) - found)
            if missing:
                raise ValueError(f"unknown evidence tweet IDs: {', '.join(missing)}")
            restricted = sorted(set(evidence).intersection(self.restricted_tweet_ids("judge_evidence")))
            if restricted:
                raise ValueError(f"content-policy-ineligible evidence tweet IDs: {', '.join(restricted)}")
        with self.connect() as connection:
            cursor = connection.execute("""INSERT INTO radar_judgements(created_at,action_level,horizon_24h,horizon_48h,horizon_72h,
                data_health,reason_summary,evidence_post_ids,special_event_ids,model,prompt_version,estimated_start,estimated_end,
                estimate_basis,valid_until,cycle_id,status,failure_reason,context_hash,raw_json,corpus_version,historical_case_ids)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (normalise_time(judgement.get("created_at")) or utc_now(), *values, str(judgement.get("data_health") or "UNKNOWN"),
                 str(judgement["reason_summary"]), json.dumps(evidence), json.dumps(judgement.get("special_event_ids") or []),
                 judgement.get("model"), str(judgement.get("prompt_version") or "v2-intelligence-1"),
                 normalise_time(judgement.get("estimated_start")), normalise_time(judgement.get("estimated_end")),
                 judgement.get("estimate_basis"), normalise_time(judgement.get("valid_until")), judgement.get("cycle_id"),
                 judgement.get("status", "COMPLETED"), judgement.get("failure_reason"), judgement.get("context_hash"),
                 json.dumps(judgement.get("raw") or {}, ensure_ascii=False), judgement.get("corpus_version"),
                 json.dumps(judgement.get("historical_case_ids") or [])))
            return int(cursor.lastrowid)

    def latest_judgement(self, *, as_of: str | datetime | None = None) -> dict[str, Any] | None:
        cutoff = normalise_time(as_of) if as_of else None
        with self.connect() as connection:
            if cutoff:
                row = connection.execute(
                    "SELECT * FROM radar_judgements WHERE created_at<=? ORDER BY created_at DESC,id DESC LIMIT 1",
                    (cutoff,),
                ).fetchone()
            else:
                row = connection.execute("SELECT * FROM radar_judgements ORDER BY created_at DESC,id DESC LIMIT 1").fetchone()
        if not row:
            return None
        result = dict(row); result["evidence_post_ids"] = json.loads(result["evidence_post_ids"]); result["special_event_ids"] = json.loads(result["special_event_ids"]); result["historical_case_ids"] = json.loads(result.get("historical_case_ids") or "[]"); result["raw"] = json.loads(result.pop("raw_json") or "{}")
        return result

    def judgement_is_usable(
        self,
        judgement: dict[str, Any],
        *,
        at: str | datetime | None = None,
    ) -> bool:
        reference = normalise_time(at) if at is not None else utc_now()
        if judgement.get("status") != "COMPLETED" or not judgement.get("valid_until"):
            return False
        if str(judgement["valid_until"]) < str(reference):
            return False
        evidence = {str(item) for item in judgement.get("evidence_post_ids") or []}
        return not evidence.intersection(self.restricted_tweet_ids("judge_evidence"))

    def set_state(self, key: str, value: Any) -> None:
        with self.connect() as connection:
            connection.execute("INSERT INTO pipeline_state(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                               (key, json.dumps(value, ensure_ascii=False), utc_now()))

    def get_state(self, key: str, default: Any = None) -> Any:
        with self.connect() as connection:
            row = connection.execute("SELECT value_json FROM pipeline_state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def _post(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row); result["is_reply"] = bool(result["is_reply"]); result["original_text"] = result.get("original_text") or result.get("text") or ""; result["text"] = result["original_text"]
        analysis_json = result.pop("latest_analysis_json", None); result["analysis"] = json.loads(analysis_json) if analysis_json else None
        return result

    @staticmethod
    def _event(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row); result["provenance"] = json.loads(result["provenance"]); result["evidence_post_ids"] = json.loads(result.get("evidence_post_ids") or "[]"); result["display_tone"] = "PURPLE" if result["event_type"] == "SPECIAL_RESET" else "EVENT"
        return result


def next_reset_baseline(last_full_reset: dict[str, Any] | None) -> dict[str, Any]:
    if not last_full_reset:
        return {"status": "waiting_for_verified_history", "estimated_at": None, "basis": "最近一次完整 Reset 尚无足够证据确认。"}
    occurred = datetime.fromisoformat(str(last_full_reset["occurred_at"]).replace("Z", "+00:00"))
    estimate_dt = (occurred + timedelta(days=7)).astimezone(UTC)
    return {"status": "expired" if estimate_dt < datetime.now(UTC) else "baseline",
            "estimated_at": estimate_dt.isoformat().replace("+00:00", "Z"),
            "basis": "按上次完整重置加 7 天估算；不是官方承诺或模型概率结论。"}
