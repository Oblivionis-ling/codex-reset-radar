# P0 稳定修复发布验收

截至 2026-09-28；本报告随 Alpha 5 发布 PR 更新。完整本地运行回执位于忽略目录 `runtime/p0-release-acceptance.json`，不包含凭据、模型请求体或真实语料。

## 结论与边界

- 实验：`CLOSED_NOT_ADOPTED`。原执行终态仍为 `EXECUTION_COMPLETE_WITH_INCOMPLETE_PAIR`；A1/B1 不晋级生产，Laya 不启用为决策默认，严格日期扩展轨未运行。
- P0 代码：`READY_FOR_MERGE`（发布 PR、CI、合并及标签待完成）。
- 本地运行：当前仍是 Alpha 4，P0 切换须等正式合入 main 后执行；旧服务继续可用。
- 本轮新增模型 HTTP、Laya 推理、历史重跑、微信及邮件发送均为 0；剩余 21 次预算保持未用。

## 正式修改

1. 回复上下文沿 `as_of` 使用当时可得的正文、父帖关系、作者及分析版本；迟到取得或后来修订的父帖不回填历史。父帖作者与 Tibo 回复作者分别归属。
2. Judge 请求前冻结帖子输入版本，并将正式 Reset 事件来源、分析、事件摘要、历史案例、当前周期及语料版本纳入输入快照。包括不在最近 24 帖中的事件来源。请求在途发生实质变化时拒绝迟到结果；历史 Judge 不回写或补造版本。
3. 受管理证据缺少版本、版本冲突、未来/受限/未暴露引用继续明确拒绝。必要边界兼容留在数据库及回复上下文入口，不引入一次性回放器、A1/B1、Laya 或临时补录工具。

分析、翻译和 Judge 的版本号保持：`v2-post-semantics-9-context`、`v2-zh-translation-2-context`、`v2-reset-judge-8-context-health`。以 Fake 客户端从基线和候选实际捕获的 system 文本 SHA-256 完全相同：

| 操作 | Prompt 版本 | system 文本 SHA-256 |
|---|---|---|
| 分析 | `v2-post-semantics-9-context` | `589a04c234ea99902746cb287598f61389bbe36a08951a42392b7504c1637b35` |
| 翻译 | `v2-zh-translation-2-context` | `b2acb058d4e32f10e303038559d434890403250245db343de0d2f2357e40bb02` |
| Judge | `v2-reset-judge-8-context-health` | `7c86e2fbba3537e9cf2e1da2b5628f50bce69762f18991aa59175b01daf88582` |

分析请求会明确传递目标作者与已有内容元数据，这是输入归属修复；未更换静态 Prompt 文本、版本、模型参数或颜色策略。单边时间值在现有 Web renderer 已显示为时间值（不是“未知→未知”），本次不改 renderer；无结束边界仍由现有说明表达。

## 验证

- P0 相关隔离回归：44 passed；Backend 全量：94 passed（1 条 Starlette/httpx 弃用警告，无失败）。
- Web：7 passed，类型检查与构建通过。Collector：18 passed，类型检查与构建通过；采集源码和协议未修改，Alpha 4 扩展兼容，无需重载。
- 空数据库真实 HTTP 冒烟：Alpha 5 API 健康、数据库初始化、`/api/v2/radar` 可读，模型未配置；测试进程已退出。无模型或通知请求。
- 生产备份：`runtime/backups/codex-reset-radar-v2.pre-p0-stability-20260927T191602Z.db`，SHA-256 `80ce8932b822507c53a6746aafc22a6ea9a17304da08a17974a8852679b983ac`。隔离副本与备份的 20 张表逐表行数/内容哈希相同，`integrity_check=ok`、外键错误 0。
- GitHub 干净检出、PR/CI、最终标签与本地切换结果将在发布后补入本报告；模型测试不使用真实凭据。

## 实验勘误

- W13 `X:2039248564967424483` 是不完整节选；上游阶段归一与评估侧阅读注释冲突，后者不是人工批准标签。因此它不是确认的 Judge 漏报金标准，不据此改事件或证明候选策略正确。
- S01 的 R 结果确实识别了明确时点：`2026-09-13T02:30:00Z` 写入 `estimated_start`，`estimated_end=null`。这是合成正控制，证明点值识别，不是区间预测或线上命中；不得补造结束时刻。
- 配对回放终态、预算消耗、失败及不可比较样本保持原样；完整记录仍在本地忽略目录 `runtime/review/weekly-20260922/paired-calibration-closeout/`。

## 回滚与遗留

合入前生产维持 Alpha 4；切换使用项目正式启动/停止入口，保留 Alpha 4 代码和已验证数据库备份。若 Backend/API、采集协议或数据库检查失败，只回滚运行代码，不用旧备份覆盖新采集数据。

页面视觉自动化本轮未能启动：Windows 浏览器清单连续返回 `nodeRepl.fetch request failed`，API 与 Web HTTP 检查通过但不冒称已完成浏览器实看。正式切换后的采集心跳及自然 Judge 另按运行回执记录；无新自然 Judge 不触发模型补判。
