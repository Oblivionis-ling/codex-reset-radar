# 历史档案导航

这里的日期、PID、测试数量和 PASS/PARTIAL 均是当时快照，不替代[当前文档](../README.md)。不运行旧 Mirror/Pages 脚本，不重写历史结论。正文只保留一份。

## 阅读顺序

- V2 起步：分叉记录 → Foundation → Alpha 1 发布 → 本地完整链路。
- 语料：第一轮 → 第二轮 → 标准化审核 → 人工裁定跟进 → [固定结项报告](../v2/corpus/corpus-closeout-report.md)。
- 通知：旧调研 → 准备报告；实际操作只用[当前指南](../notifications/testing-guide.md)。
- 事故：父帖修复 → UNKNOWN 现场 → [尚未结案的修复报告](../maintenance/judge-context-and-health-fix-report.md)。
- [V1 最终状态](../v1/v1-final-status.md)、[V1 迁移操作](../v1/v1-to-v2-migration.md)均原样保留历史含义。
- [工作区整理结项](workspace/workspace-optimization-report-20260921.md)。

## 固定证据例外

`docs/v2/corpus/corpus-closeout-report.md` 被 `runtime/review/corpus-closeout-20260918/corpus-closeout-acceptance.json` 的 artifacts/report 路径和 SHA256 绑定，PINNED_KEEP，不搬、不改字节。
`data/corpus` 与 `runtime/review` 保存独立参考、人工裁定及真实程序结果，不散拆、不做 TTL 清理。
原位置保留不是又一份“当前说明”。

## 普通历史旧路径映射

本轮已执行任务原件从 `docs/maintenance/crr-workspace-optimization-task-20260921.md`
原样归档至 [任务书](tasks/crr-workspace-optimization-task-20260921.md)。

历史正文中的路径/命令可能描述当时环境，不做全局替换。可导航的普通 Markdown 链接随移动调整；固定报告中的失效旧路径以本表定位。

| 原路径 | 当前位置 |
| --- | --- |
| `docs/v2/remote-main-divergence-report-2026-09-13.md` | [remote-main-divergence-report-2026-09-13.md](v2-foundation/remote-main-divergence-report-2026-09-13.md) |
| `docs/v2/v2-foundation-alpha1-report.md` | [v2-foundation-alpha1-report.md](v2-foundation/v2-foundation-alpha1-report.md) |
| `docs/v2/v2-alpha1-publication-report.md` | [v2-alpha1-publication-report.md](v2-foundation/v2-alpha1-publication-report.md) |
| `docs/v2/v2-local-full-pipeline-report.md` | [v2-local-full-pipeline-report.md](v2-foundation/v2-local-full-pipeline-report.md) |
| `docs/v2/corpus-and-wechat-phase-report.md` | [corpus-and-wechat-phase-report.md](corpus/corpus-and-wechat-phase-report.md) |
| `docs/v2/migration-from-v1.md` | [v1-to-v2-migration.md](../v1/v1-to-v2-migration.md) |
| `docs/v2/corpus/corpus-standardization-review-report.md` | [corpus-standardization-review-report.md](corpus/corpus-standardization-review-report.md) |
| `docs/v2/corpus/human-adjudication-followup-20260918.md` | [human-adjudication-followup-20260918.md](corpus/human-adjudication-followup-20260918.md) |
| `docs/v2/corpus/historical-corpus-report.md` | [historical-corpus-report.md](corpus/historical-corpus-report.md) |
| `docs/v2/corpus/historical-corpus-round2-report.md` | [historical-corpus-round2-report.md](corpus/historical-corpus-round2-report.md) |
| `docs/v2/corpus/historical-evidence-disposition.md` | [historical-evidence-disposition.md](corpus/historical-evidence-disposition.md) |
| `docs/v2/corpus/corpus-coverage.md` | [corpus-coverage.md](corpus/corpus-coverage.md) |
| `docs/v2/corpus/source-register.md` | [source-register.md](corpus/source-register.md) |
| `docs/v2/corpus/third-party-source-verification.md` | [third-party-source-verification.md](corpus/third-party-source-verification.md) |
| `docs/v2/corpus/import-and-verification.md` | [import-and-verification.md](corpus/import-and-verification.md) |
| `docs/v2/notifications/wechat-channel-research.md` | [wechat-channel-research.md](notifications/wechat-channel-research.md) |
| `docs/maintenance/notification-prep-and-cleanup.md` | [notification-prep-and-cleanup.md](notifications/notification-prep-and-cleanup.md) |
| `docs/maintenance/reply-context-fix-report.md` | [reply-context-fix-report.md](incidents/reply-context-fix-report.md) |
| `docs/maintenance/crr-status-20260921.md` | [crr-status-20260921.md](incidents/crr-status-20260921.md) |
| `docs/notification_preparation_and_workspace_cleanup.md` | [notification_preparation_and_workspace_cleanup.md](tasks/notification_preparation_and_workspace_cleanup.md) |
| `docs/maintenance/project-directory-and-document-inventory-20260921.md` | [project-directory-and-document-inventory-20260921.md](workspace/project-directory-and-document-inventory-20260921.md) |
| `docs/phase-g-screenshots/overview-en-desktop.png` | [overview-en-desktop.png](../v1/design/phase-g-screenshots/overview-en-desktop.png) |
| `docs/phase-g-screenshots/overview-zh-desktop.png` | [overview-zh-desktop.png](../v1/design/phase-g-screenshots/overview-zh-desktop.png) |
| `docs/phase-g-screenshots/overview-zh-mobile.png` | [overview-zh-mobile.png](../v1/design/phase-g-screenshots/overview-zh-mobile.png) |
| `docs/phase-g-screenshots/resets-zh-desktop.png` | [resets-zh-desktop.png](../v1/design/phase-g-screenshots/resets-zh-desktop.png) |
| `docs/phase-g-screenshots/tweets-zh-desktop.png` | [tweets-zh-desktop.png](../v1/design/phase-g-screenshots/tweets-zh-desktop.png) |

## 历史引用的边界

V1 早期资料仍可能引用当年的 fixtures、截图和启动路径。逐链接检查结果保存在本地 `runtime/workspace-cleanup-20260921/link-check.json`，不得据此宣称所有历史链接可用。当前 12 份规范和导航必须无失效本地 Markdown 链接。
