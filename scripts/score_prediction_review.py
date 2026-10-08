"""Freeze explicit evaluation membership / score verified, read-only packages."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1] / "apps" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.prediction_scoring import (  # noqa: E402
    ScoringContractError, evaluate_review, freeze_evaluation_set, verify_assessment,
)
from app.review_common import canonical_bytes  # noqa: E402
from app import review_export  # noqa: E402


MAX_JSON_BYTES = 100 * 1024 * 1024


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic offline scoring; package validity is not prediction quality.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("freeze", "score"):
        command = commands.add_parser(name, help="freeze explicit event/series membership" if name == "freeze" else "score a frozen evaluation set")
        command.add_argument("--package", type=Path, required=True, help="Existing review ZIP; public verified loader, no database writes")
        if name == "freeze":
            command.add_argument("--definition", type=Path, required=True, help="Explicit membership JSON")
        else:
            selection = command.add_mutually_exclusive_group(required=True)
            selection.add_argument("--set", type=Path, help="Previously frozen evaluation-set JSON sidecar")
            selection.add_argument("--set-id", help="Frozen set ID embedded in the verified package")
        command.add_argument("--out", type=Path, required=True, help="New JSON sidecar; existing files are never replaced")
        command.add_argument("--staging-dir", type=Path, required=True, help="Explicit existing matter _tmp directory, same volume as --out")
    verify = commands.add_parser("verify-assessment", help="Recompute an embedded result, not just ZIP integrity")
    verify.add_argument("--package", type=Path, required=True)
    verify.add_argument("--assessment-id", required=True)
    return parser


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ScoringContractError("duplicate_json_key")
        result[key] = value
    return result


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ScoringContractError("input_json_not_regular_file")
    with path.open("rb") as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ScoringContractError("input_json_size_limit_exceeded")
    def reject_constant(_value):
        raise ScoringContractError("nonfinite_json_value")
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError):
        raise ScoringContractError("input_json_invalid") from None
    if not isinstance(result, dict):
        raise ScoringContractError("input_json_must_be_object")
    return result


def _load_review(package: Path) -> dict[str, Any]:
    # One shared reader/verifier owns ZIP member, hash, reference and privacy
    # validation. Do not maintain another ZIP loader or weaken its checks here.
    loader = getattr(review_export, "load_verified_review", None)
    if loader is None:
        raise ScoringContractError("shared_verified_loader_unavailable")
    loaded = loader(package)
    if not isinstance(loaded, dict) or not isinstance(loaded.get("collections"), dict) or not isinstance(loaded.get("manifest"), dict):
        raise ScoringContractError("shared_verified_loader_contract_mismatch")
    verification = loaded.get("verification")
    if not isinstance(verification, dict) or verification.get("valid") is not True:
        raise ScoringContractError("source_package_not_verified")
    review = dict(loaded["collections"])
    review["source_binding"] = loaded["manifest"].get("source_binding")
    review["package_binding"] = {key: loaded.get(key) for key in ("source_package_sha256", "manifest_sha256")}
    return review


def _publish_json(document: dict[str, Any], output: Path, stage_root: Path) -> None:
    stage_root = stage_root.resolve(strict=True)
    parent = output.parent.resolve(strict=True)
    if not stage_root.is_dir() or not parent.is_dir() or output.suffix.lower() != ".json":
        raise ScoringContractError("json_output_or_staging_path_invalid")
    if os.stat(stage_root).st_dev != os.stat(parent).st_dev:
        raise ScoringContractError("staging_and_output_must_share_volume")
    if output.exists() or output.is_symlink():
        raise ScoringContractError("output_path_already_exists")
    data = canonical_bytes(document)
    if len(data) > MAX_JSON_BYTES:
        raise ScoringContractError("output_json_size_limit_exceeded")
    review_export._privacy_scan(data)
    stage = Path(tempfile.mkdtemp(prefix="prediction-score-", dir=stage_root))
    try:
        candidate = stage / "result.json"
        with candidate.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if _read_json(candidate) != document:
            raise ScoringContractError("staged_json_verification_failed")
        try:
            os.link(candidate, output)
        except FileExistsError:
            raise ScoringContractError("output_path_already_exists") from None
        except OSError:
            raise ScoringContractError("atomic_no_clobber_publish_failed") from None
    finally:
        # Only this freshly-created exact child, never the caller's existing dir.
        shutil.rmtree(stage, ignore_errors=True)


def _embedded(review: dict[str, Any], collection: str, identifier: str) -> dict[str, Any]:
    matches = [row for row in review.get(collection, []) if row.get("id") == identifier]
    if len(matches) != 1:
        raise ScoringContractError("embedded_record_missing_or_ambiguous")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        review = _load_review(args.package)
        if args.command == "verify-assessment":
            result = verify_assessment(review, _embedded(review, "assessments", args.assessment_id))
            print(json.dumps(result, sort_keys=True))
            return 0
        document = (freeze_evaluation_set(review, _read_json(args.definition), review["source_binding"])
                    if args.command == "freeze" else evaluate_review(review, _read_json(args.set) if args.set else _embedded(review, "evaluation_sets", args.set_id)))
        _publish_json(document, args.out, args.staging_dir)
        print(json.dumps({"output": str(args.out), "schema_version": document["schema_version"],
                          "set_hash": document["set_hash"], "record_sha256": document["record_sha256"],
                          "assessment_hash": document.get("assessment_hash"), "package_verified": True,
                          "prediction_quality_pass": None}, ensure_ascii=False, sort_keys=True))
        return 0
    except ScoringContractError as error:
        print(json.dumps({"error": str(error), "published": False}, sort_keys=True))
        return 2
    except review_export.ReviewExportError:
        print(json.dumps({"error": "review_package_or_privacy_validation_failed", "published": False}, sort_keys=True))
        return 2
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        # Never print underlying private filesystem paths or exception summaries.
        print(json.dumps({"error": "scoring_input_or_io_failed", "published": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
