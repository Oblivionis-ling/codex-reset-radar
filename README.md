# Codex Reset Radar

本地优先的 Tibo 公开推文采集、Reset 事件与 DeepSeek Judge 系统。现用应用在 `apps/backend`、`apps/web`、`apps/collector-extension`，当前数据库在 `runtime/data/codex-reset-radar-v2.db`。

接受版本 Alpha 4；未发布修复以实际加载指纹及维护报告区分。GitHub 仅用于源码和 CI，不是数据链路，不启用 Mirror/Pages。

## 日常入口

- 启动：`start-v2-local.bat`
- 停止：`stop-v2-local.bat`（只操作验证归属的本项目进程）
- 通知测试：`test-notifications.bat`（默认菜单不发送）

[完整文档导航](docs/README.md) · [安装与运行](docs/v2/local-development.md) · [通知测试指南](docs/notifications/testing-guide.md)

Web：<http://127.0.0.1:5173>。通知准备代码未接生产 Judge，真实发送必须显式确认。凭据只在本地 `.env`，不要上传或贴到聊天。

数据保留和公开边界见 [数据政策](data/README.md)。历史档案从文档导航进入，不能照旧报告恢复已退役运行链。
