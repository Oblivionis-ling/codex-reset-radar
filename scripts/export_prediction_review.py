from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, date, datetime, time
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "apps" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.review_export import (  # noqa: E402
    ReviewExportError,
    ReviewPackageValidationError,
    export_review,
    preview_review,
    review_local_zone,
)
from app.review_reader import DEFAULT_MAX_RECORDS, ReviewRangeTooLarge, ReviewReadError  # noqa: E402


def parse_user_time(value: str) -> datetime:
    raw = value.strip()
    try:
        if len(raw) == 10:
            parsed = datetime.combine(date.fromisoformat(raw), time.min, review_local_zone())
        else:
            parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=review_local_zone())
        return parsed.astimezone(UTC)
    except ValueError as error:
        raise argparse.ArgumentTypeError("时间需为 ISO 日期或日期时间；无时区时按 Asia/Shanghai 解释") from error


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _add_selection_arguments(parser: argparse.ArgumentParser, *, include_publish: bool) -> None:
    parser.add_argument("--database", type=Path, required=True, help="既存 SQLite DB；以 mode=ro 打开，不创建或初始化")
    parser.add_argument("--from", dest="from_at", type=parse_user_time, help="活动窗口起点，包含；日期/无时区按 Asia/Shanghai")
    parser.add_argument("--to", dest="to_at", type=parse_user_time, help="活动窗口终点，不包含；日期/无时区按 Asia/Shanghai")
    parser.add_argument("--freeze-at", type=parse_user_time, required=True, help="独立资料冻结截止；日期/无时区按 Asia/Shanghai")
    parser.add_argument("--series", "--series-id", dest="series_id", help="选择完整预测系列及其依赖")
    parser.add_argument("--high-water", type=int, help="固定 ledger 序号上限")
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    if include_publish:
        parser.add_argument("--out", type=Path, required=True, help="目标 ZIP；父目录须已存在，不能覆盖已有文件")
        parser.add_argument("--staging-dir", type=Path, required=True, help="调用方明确指定的独立 staging 目录（事项 _tmp 内）")


def _selection(args: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[dict[str, object], str]:
    start = _format_time(args.from_at) if args.from_at else None
    end = _format_time(args.to_at) if args.to_at else None
    if (start is None) != (end is None):
        parser.error("--from 与 --to 必须同时提供；也可只指定 --series")
    if start is None and not args.series_id:
        parser.error("必须提供 --from/--to 时间范围或 --series")
    selection = {"start": start, "end": end, "series_id": args.series_id}
    return selection, _format_time(args.freeze_at)


def _open_readonly(path: Path) -> sqlite3.Connection:
    database_path = path.expanduser().resolve(strict=True)
    if not database_path.is_file():
        raise FileNotFoundError("database_does_not_exist")
    uri = database_path.as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview, export, and verify a read-only prediction review package.")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="只读检查数据库、范围、目标路径与同卷 staging")
    _add_selection_arguments(prepare, include_publish=True)
    preview = commands.add_parser("preview", help="只读预览范围、记录数、依赖和缺口")
    _add_selection_arguments(preview, include_publish=False)
    export = commands.add_parser("export", help="生成并校验 ZIP，再原子发布")
    _add_selection_arguments(export, include_publish=True)
    verify = commands.add_parser("verify", help="校验已生成的复盘 ZIP")
    verify.add_argument("--package", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "verify":
        try:
            from app.review_export import verify_review

            result = verify_review(args.package)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
            return 0
        except FileNotFoundError:
            print(json.dumps({"valid": False, "error": "review_package_not_found"}, ensure_ascii=False))
            return 2
        except ReviewPackageValidationError as error:
            print(json.dumps({"valid": False, "error": str(error)}, ensure_ascii=False))
            return 2

    selection, freeze_at = _selection(args, parser)
    if args.max_records <= 0:
        parser.error("--max-records must be positive")
    connection = None
    try:
        connection = _open_readonly(args.database)
        if args.command == "prepare":
            output, staging = args.out.expanduser().absolute(), args.staging_dir.expanduser().resolve(strict=True)
            if not staging.is_dir() or not output.parent.resolve(strict=True).is_dir():
                raise ReviewExportError("staging_and_output_parent_must_exist")
            if output.exists():
                raise FileExistsError("output_path_already_exists")
            import os

            if os.stat(staging).st_dev != os.stat(output.parent.resolve(strict=True)).st_dev:
                raise ReviewExportError("staging_and_output_must_share_volume")
        result = preview_review(connection, selection, freeze_at, args.high_water, max_records=args.max_records)
        if args.command == "export":
            result = export_review(
                connection,
                selection,
                freeze_at,
                args.out,
                args.staging_dir,
                args.high_water,
                max_records=args.max_records,
            )
        elif args.command == "prepare":
            result["publish_preflight"] = "ready_same_volume_no_output_created"
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except FileNotFoundError:
        print(json.dumps({"error": "database_or_required_path_does_not_exist"}, ensure_ascii=False))
        return 2
    except ReviewRangeTooLarge as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2
    except ReviewReadError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2
    except ReviewPackageValidationError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2
    except ReviewExportError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2
    except FileExistsError:
        print(json.dumps({"error": "output_path_already_exists"}, ensure_ascii=False))
        return 2
    except sqlite3.Error:
        print(json.dumps({"error": "readonly_database_open_or_read_failed"}, ensure_ascii=False))
        return 2
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())

