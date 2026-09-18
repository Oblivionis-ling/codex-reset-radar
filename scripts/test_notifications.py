from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "apps" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import load_settings  # noqa: E402
from app.logging_runtime import RuntimeLog  # noqa: E402
from app.notifications.config import load_notification_settings  # noqa: E402
from app.notifications.ledger import NotificationLedger  # noqa: E402
from app.notifications.models import DeliveryState, NotificationMessage, NotificationResult  # noqa: E402
from app.notifications.registry import CHANNELS, build_adapter, missing_configuration  # noqa: E402
from app.notifications.selftest import run_offline_selftest  # noqa: E402
from app.notifications.service import NotificationDispatcher  # noqa: E402
from app.notifications.transport import HttpTransport  # noqa: E402


def _json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def show_status() -> int:
    settings = load_notification_settings()
    _json(
        {
            "safety": {
                "default_network": "BLOCKED",
                "startup_sends": 0,
                "prepare_sends": 0,
                "check_sends": 0,
                "preview_sends": 0,
                "selftest_real_sends": 0,
            },
            "channels": settings.channel_status(),
        }
    )
    return 0


def check_configuration() -> int:
    settings = load_notification_settings()
    _json(
        {
            channel: {
                "status": "READY_FOR_MANUAL_TEST" if not (missing := missing_configuration(channel, settings)) else "NEEDS_USER_SETUP",
                "missing": missing,
            }
            for channel in CHANNELS
        }
    )
    return 0


def preview() -> int:
    message = NotificationMessage.test_message()
    _json({"title": message.title, "body": message.body, "url": message.url, "real_send": False})
    return 0


async def selftest() -> int:
    statuses = await run_offline_selftest()
    receipt = {
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "network": "IN_MEMORY_ONLY",
        "real_send_count": 0,
        "channels": statuses,
    }
    receipt_path = ROOT / "runtime" / "notification-tests" / "latest-selftest.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(receipt_path)
    receipt["receipt_path"] = str(receipt_path)
    _json(receipt)
    return 0


async def live_send(channel: str, *, fallback_email: bool) -> int:
    settings = load_notification_settings()
    missing = missing_configuration(channel, settings)
    if fallback_email:
        missing.extend(missing_configuration("smtp_email", settings))
    if missing:
        print("配置不完整：" + ", ".join(dict.fromkeys(missing)))
        return 2
    phrase = f"SEND {channel}"
    print("即将发送一条标题和正文均注明‘测试，非真实 Reset 预警’的真实消息。")
    print(f"目标渠道：{channel}；邮件兜底：{'是' if fallback_email else '否'}")
    if input(f"输入 {phrase} 确认，其他输入取消：").strip() != phrase:
        print("已取消；未发送任何消息。")
        return 3

    transport = HttpTransport(
        network_enabled=True,
        timeout_seconds=settings.timeout_seconds,
        retries=settings.http_retries,
    )
    ledger = NotificationLedger(settings.ledger_path)
    dispatcher = NotificationDispatcher(ledger)
    runtime = load_settings()
    runtime_log = RuntimeLog(runtime.log_dir, runtime.log_retention_days, runtime.log_max_bytes)
    dedup_key = f"manual-test:{channel}:{uuid.uuid4()}"
    try:
        primary = build_adapter(channel, settings, transport if channel != "smtp_email" else None, network_enabled=True)
        if fallback_email and channel != "smtp_email":
            email = build_adapter("smtp_email", settings, None, network_enabled=True)
            primary_result, email_result = await dispatcher.send_with_email_fallback(
                primary, email, NotificationMessage.test_message(), dedup_key=dedup_key
            )
            result: object = {"primary": primary_result.as_dict(), "email_fallback": email_result.as_dict() if email_result else None}
        else:
            current = await dispatcher.send_once(primary, NotificationMessage.test_message(), dedup_key=dedup_key)
            settled = await dispatcher.settle(primary, current)
            if settled.state.value != "DUPLICATE":
                ledger.record(dedup_key, settled)
            result = settled.as_dict()
        runtime_log.write(
            "notification",
            "manual_notification_test",
            metadata={"channel": channel, "fallback_email": fallback_email, "dedup_key": dedup_key},
        )
        _json(result)
        print("程序结果不等于手机已送达；请按测试指南记录微信/锁屏/正文/延迟观察。")
        return 0
    finally:
        await transport.close()


class _SimulatedWechatResult:
    channel = "simulated_wechat"

    def __init__(self, state: DeliveryState) -> None:
        self.state = state

    async def send(self, _message: NotificationMessage) -> NotificationResult:
        return NotificationResult(
            self.channel,
            self.state,
            self.state != DeliveryState.FAILED,
            detail="local simulation; no WeChat provider request was made",
        )


async def live_email_fallback_test(reason: str) -> int:
    settings = load_notification_settings()
    missing = missing_configuration("smtp_email", settings)
    if missing:
        print("配置不完整：" + ", ".join(missing))
        return 2
    phrase = "SEND smtp_fallback"
    print("微信结果仅在本地模拟；不会访问微信渠道。确认后会真实发送一封 SMTP 保底测试邮件。")
    if input(f"输入 {phrase} 确认，其他输入取消：").strip() != phrase:
        print("已取消；未发送任何消息。")
        return 3
    state = DeliveryState.FAILED if reason == "failure" else DeliveryState.UNKNOWN
    ledger = NotificationLedger(settings.ledger_path)
    dispatcher = NotificationDispatcher(ledger, query_attempts=0)
    email = build_adapter("smtp_email", settings, None, network_enabled=True)
    primary, fallback = await dispatcher.send_with_email_fallback(
        _SimulatedWechatResult(state),
        email,
        NotificationMessage.test_message(),
        dedup_key=f"manual-fallback:{reason}:{uuid.uuid4()}",
    )
    runtime = load_settings()
    RuntimeLog(runtime.log_dir, runtime.log_retention_days, runtime.log_max_bytes).write(
        "notification",
        "manual_email_fallback_test",
        metadata={"simulated_wechat_state": state.value, "real_wechat_send": False},
    )
    _json({"simulated_wechat": primary.as_dict(), "email_fallback": fallback.as_dict() if fallback else None})
    print("SMTP 接受不等于邮箱已收到；请检查收件箱/垃圾箱并记录延迟。")
    return 0


def recent() -> int:
    settings = load_notification_settings()
    _json(NotificationLedger(settings.ledger_path).recent())
    return 0


def interactive_menu() -> int:
    while True:
        print(
            "\nCodex Reset Radar 通知测试（默认不发送）\n"
            "1. 查看渠道准备状态\n"
            "2. 本地检查配置\n"
            "3. 预览测试消息\n"
            "4. 离线自测（拦截所有网络）\n"
            "5. 选择一个渠道真实发送\n"
            "6. 查看本地结果记录\n"
            "7. 模拟微信失败/未确认并真实发送一封 SMTP 保底邮件\n"
            "0. 退出"
        )
        choice = input("请选择：").strip()
        if choice == "1":
            show_status()
        elif choice == "2":
            check_configuration()
        elif choice == "3":
            preview()
        elif choice == "4":
            asyncio.run(selftest())
        elif choice == "5":
            print("可选：" + ", ".join(CHANNELS))
            channel = input("渠道：").strip()
            if channel not in CHANNELS:
                print("未知渠道。")
                continue
            fallback = channel != "smtp_email" and input("微信失败/未确认时转独立 SMTP？输入 YES 启用：").strip() == "YES"
            asyncio.run(live_send(channel, fallback_email=fallback))
        elif choice == "6":
            recent()
        elif choice == "7":
            reason = input("输入 failure 模拟明确失败，输入 unknown 模拟结果未确认：").strip().lower()
            if reason not in {"failure", "unknown"}:
                print("无效模拟类型。")
                continue
            asyncio.run(live_email_fallback_test(reason))
        elif choice == "0":
            print("已退出；没有因退出而发送消息。")
            return 0
        else:
            print("无效选项。")


def parser() -> argparse.ArgumentParser:
    current = argparse.ArgumentParser(description="Codex Reset Radar notification preparation and manual test entry")
    sub = current.add_subparsers(dest="command")
    for name in ("prepare", "status", "check", "preview", "selftest", "recent"):
        sub.add_parser(name)
    send = sub.add_parser("send")
    send.add_argument("--channel", required=True, choices=CHANNELS)
    send.add_argument("--live", action="store_true", help="required in addition to interactive confirmation")
    send.add_argument("--fallback-email", action="store_true")
    fallback = sub.add_parser("fallback-test")
    fallback.add_argument("--reason", choices=("failure", "unknown"), default="failure")
    fallback.add_argument("--live", action="store_true", help="required in addition to interactive confirmation")
    return current


def main() -> int:
    args = parser().parse_args()
    if args.command is None:
        return interactive_menu()
    if args.command in {"prepare", "status"}:
        return show_status()
    if args.command == "check":
        return check_configuration()
    if args.command == "preview":
        return preview()
    if args.command == "selftest":
        return asyncio.run(selftest())
    if args.command == "recent":
        return recent()
    if args.command == "send":
        if not args.live:
            print("拒绝发送：真实发送必须显式提供 --live，并仍需交互确认。")
            return 2
        return asyncio.run(live_send(args.channel, fallback_email=args.fallback_email))
    if args.command == "fallback-test":
        if not args.live:
            print("拒绝发送：SMTP 兜底测试必须显式提供 --live，并仍需交互确认。")
            return 2
        return asyncio.run(live_email_fallback_test(args.reason))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
