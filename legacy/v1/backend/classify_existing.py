"""Classify the existing local Tweet corpus once, without touching the collector."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.classifiers.service import classify_tweet_ids
from app.config import get_settings
from app.database import create_database
from app.models import Tweet


async def main() -> None:
    settings = get_settings()
    engine, session_factory = create_database(settings.database_url, settings.database_path)
    try:
        with session_factory() as session:
            tweet_ids = list(session.scalars(select(Tweet.tweet_id).order_by(Tweet.discovered_at.asc())).all())
        result = await classify_tweet_ids(session_factory, tweet_ids, settings=settings)
        print(result)
    finally:
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

