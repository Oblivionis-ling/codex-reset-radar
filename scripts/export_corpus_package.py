from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.corpus_standard import PackageMetadata, export_package, file_sha256  # noqa: E402
from app.db import Database  # noqa: E402
from app.intelligence import ANALYSIS_PROMPT_VERSION, JUDGE_PROMPT_VERSION, TRANSLATION_PROMPT_VERSION  # noqa: E402
from app.version import APP_VERSION  # noqa: E402


def git_output(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPOSITORY_ROOT, check=True, text=True, capture_output=True, encoding="utf-8"
    ).stdout.strip()


def worktree_fingerprint() -> str:
    import hashlib

    status = git_output("status", "--porcelain=v1", "--untracked-files=all")
    digest = hashlib.sha256()
    digest.update(status.encode("utf-8"))
    for line in status.splitlines():
        relative = line[3:].split(" -> ")[-1]
        path = REPOSITORY_ROOT / relative
        if path.is_file():
            digest.update(relative.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a deterministic Codex Reset Radar corpus review package.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--frozen-at", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--gpt-runtime",
        default="Codex main model (GPT family); exact deployment identifier is not exposed to this task",
    )
    args = parser.parse_args()
    database_path = args.database.resolve()
    database = Database(database_path)
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    manifest = export_package(
        database,
        args.output.resolve(),
        PackageMetadata(
            package_id=args.package_id,
            frozen_at=args.frozen_at,
            generated_at=generated_at,
            source_database=str(database_path),
            source_database_sha256=file_sha256(database_path),
            git_head=git_output("rev-parse", "HEAD"),
            worktree_fingerprint=worktree_fingerprint(),
            app_version=APP_VERSION,
            corpus_version=database.corpus_version(),
            model=args.model,
            prompt_versions={
                "analysis": ANALYSIS_PROMPT_VERSION,
                "translation": TRANSLATION_PROMPT_VERSION,
                "judge": JUDGE_PROMPT_VERSION,
            },
            gpt_runtime=args.gpt_runtime,
        ),
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
