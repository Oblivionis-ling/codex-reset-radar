import type { ActionLevel } from "./api";

export function tone(level: ActionLevel): string {
  return level.toLowerCase();
}

export function actionCopy(level: ActionLevel): string {
  const copy: Record<ActionLevel, string> = {
    GREEN: "正常使用",
    YELLOW: "开始关注，可以适当增加使用",
    ORANGE: "Reset 已比较临近，积极使用 Codex",
    RED: "强烈近期 Reset 信号，尽量消耗额度",
    UNKNOWN: "数据不足 / 当前无法判断"
  };
  return copy[level];
}

export function formatTime(value: string | null): string {
  if (!value) return "等待可信历史";
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString("zh-CN", { hour12: false }) : "未知";
}

export function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
