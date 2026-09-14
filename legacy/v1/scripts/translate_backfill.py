from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.classifiers.service import translate_tweet_ids
from app.main import create_app
from app.models import Classification, Tweet


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate recent and high-value Tweets for the public Dashboard")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    app = create_app()
    try:
        with app.state.session_factory() as session:
            recent_ids = session.scalars(
                select(Tweet.tweet_id).order_by(Tweet.created_at.desc(), Tweet.discovered_at.desc()).limit(max(1, args.limit))
            ).all()
            signal_ids = session.scalars(
                select(Classification.tweet_id)
                .where(
                    Classification.classifier_type == "final",
                    Classification.category.in_(
                        [
                            "reset_hint",
                            "reset_announcement",
                            "reset_in_progress",
                            "reset_confirmed",
                            "reset_denial",
                            "quota_information",
                        ]
                    ),
                )
                .order_by(Classification.created_at.desc(), Classification.id.desc())
            ).all()
        result = asyncio.run(
            translate_tweet_ids(
                app.state.session_factory,
                list(dict.fromkeys([*recent_ids, *signal_ids])),
                force=args.force,
            )
        )
        print(result)
        return 0 if result["failed"] == 0 else 1
    finally:
        app.state.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
