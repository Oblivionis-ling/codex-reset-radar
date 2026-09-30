# P0 稳定修复发布验收

截至 2026-09-30；本报告记录 Alpha 5 的正式合入和本地切换。9 月 28 日的离线验收保留为历史阶段证据。完整本地回执位于 `D:\work\20260828-CodexResetRadar\runtime\p0-release-acceptance.json`（Git 忽略）；本次切换证据位于 `runtime/p0-rollout-20260930/`，不公开凭据、请求体或真实语料。

## 结论与边界

- 实验：`CLOSED_NOT_ADOPTED`。原执行终态仍为 `EXECUTION_COMPLETE_WITH_INCOMPLETE_PAIR`；A1/B1 不晋级生产，Laya 不启用为决策默认，严格日期扩展轨未运行。
- P0 代码：`RELEASED`。[PR #8](https://github.com/Oblivionis-ling/codex-reset-radar/pull/8) 正常合入 `main`，功能合入提交 `e353bbf55b9a3cbff635749ee4ba3192c3606341`；PR CI 和 main CI 的 Backend/Web/Collector 均通过。应用版本为 `2.0.0-alpha.5`，标签目标及后续仅文档提交记入本地回执。
- 本地运行：`PARTIAL_VERIFICATION`。根目录已安全切换至正式 main；Backend、Web 代理、三路心跳、数据库和自然 Judge 验收通过。唯一未完成项是浏览器实际页面视觉核验，工具因不能可靠确认 URL 自动停止。
- 主动实验/诊断/验收模型 HTTP、Laya 推理、历史重跑、微信及邮件发送均为 0；剩余 21 次实验预算保持未用。恢复日常调度后，自然执行 3 次近期帖分析、3 次翻译和 1 次 Judge，共 7 次 HTTP，失败 0；这些单独记录，不冒称本次上线完全没有模型请求。

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
- 干净 Git worktree（无 `.env`、运行数据库、Laya 或实验目录）从锁定依赖全新安装后，Backend 94 passed、Web 7 passed、Collector 18 passed；Web/Collector 类型检查、构建通过。空库 Alpha 5 HTTP 冒烟通过，模型关闭，测试进程退出。
- 本地发布提交：`029ed1b`（P0 修复与回归）、`1e686db`（Alpha 5 版本/文档）；父提交 `2f6f27bb3ccf80a84a9fa6818596b528358fe75c`。工作树与文件白名单已通过 `git diff --check`，秘密模式扫描 0 命中；未包含周回放、A1/B1、Laya、运行库或临时补录工具。
- 9 月 28 日 GitHub 直连失败，发布当时停在本地。9 月 30 日确认 Windows 浏览器启用本地系统代理，而 Git 没有使用它；为本仓库设置 GitHub 专用代理后，`ls-remote`、fetch 和 push 均成功，远端发布分支 SHA 与本地 `0e35afe` 一致。只修改本地 Git 配置，无密钥、全局代理或认证变更。[PR CI](https://github.com/Oblivionis-ling/codex-reset-radar/actions/runs/36686987946) 和[功能合入 main CI](https://github.com/Oblivionis-ling/codex-reset-radar/actions/runs/36687349623) 均成功。

## 合入前生产现场

本轮发布前只读 API 检查记录：Backend Alpha 4，进程 PID 20968（父进程 18952），Web PID 4728；Web `5173` 和 API `8787` 可读。最后一次健康快照时间为 `2026-09-27T20:02:09Z`，Profile/Replies/Search 均 `FRESH`。数据库帖子 436、正式事件 15、候选 7、任务 410、Judge 429；最近 Judge #429 为 `YELLOW / YELLOW / ORANGE / ORANGE`，验证 `VALID`，判断时与当前数据健康均为 `HEALTHY`，有效期至 `2026-09-27T21:19:50Z`。这些仅是切换前基线，不是 Alpha 5 运行证据；本轮没有生产数据库写入或服务重启。

## 实验勘误

- W13 `X:2039248564967424483` 是不完整节选；上游阶段归一与评估侧阅读注释冲突，后者不是人工批准标签。因此它不是确认的 Judge 漏报金标准，不据此改事件或证明候选策略正确。
- S01 的 R 结果确实识别了明确时点：`2026-09-13T02:30:00Z` 写入 `estimated_start`，`estimated_end=null`。这是合成正控制，证明点值识别，不是区间预测或线上命中；不得补造结束时刻。
- 配对回放终态、预算消耗、失败及不可比较样本保持原样；完整记录仍在本地忽略目录 `runtime/review/weekly-20260922/paired-calibration-closeout/`。

## 9 月 30 日实际切换验收

- 原实验改动按明确的 12 个已跟踪文件保存为本地检查点 `8ef93f1`，仍在 `experiment/2026-weekly-replay`，没有推送或混入 main。用户的未跟踪任务书和样本原件留在原目录；实验报告另有本地可读副本 `local-archive/closed-weekly-experiment-20260930/`，原始回放和预算记录未修改。
- 切换前一致性备份：`runtime/backups/codex-reset-radar-v2.pre-alpha5-20260930T080809Z.db`，SHA-256 `c151c11c0172d3b8aff7a3173b8a170cdba4f00caf1ea908af06c582ccdfbb2a`；完整性 `ok`、外键错误 0。本地 `.env` 也单独备份，不提交。
- 使用原项目安全停启入口，只停止核实归属的旧 Backend/Web；根目录 main 快进至功能合入提交后，通过 WMI 脱离启动。Backend PID 18612，启动 `2026-09-30T08:12:38Z`；Web PID 6488。现有根目录启动/停止入口和生产数据库路径不变，未依赖发布 worktree。
- API 返回 Alpha 5、功能合入提交及实际加载指纹 `a178cd390dfb1077`，回复上下文版本 `reply-context-v2`。分析/翻译/Judge Prompt 维持上表基线；没有加载 Laya。
- 只读采集观察覆盖多个正常 60 秒周期：Profile 在 08:13/08:15/08:17 UTC 的 sequence 为 19984/19988/19992，Replies 为 10017/10019/10021；Search 同期分别新鲜，跨扫描页面 instance 的变化如实保留。三路均为 `FRESH`，健康 API/Judge 均为 `HEALTHY`。详细观察保存在本地回执，不伪造新回复抓取。
- 正常启动检查复用已有任务，仅 3 条近期实时帖的新输入版本正常处理；没有恢复终止失败任务或历史批量任务。自然 Judge #584 于 `2026-09-30T08:13:30Z` 生成，有效至 `10:13:30Z`，Prompt `v2-reset-judge-8-context-health`，38 个输入版本，校验 `VALID`。Backend 与 Web 代理返回同一条完整结果，等级 `GREEN/GREEN/GREEN/YELLOW`；等级只作为本次结果记录，不作为发布验收标准。
- 切换前后帖子 504、正式事件 15、周期 13、当前周期 214 均未改变；事件和周期内容哈希完全相同。任务 569→572、分析 376→379、Judge 583→584，恰好对应上述自然处理；生产库完整性 `ok`、外键错误 0。通知发送 0。
- 浏览器视觉工具可列出现有 Dashboard 窗口，但捕获状态时自动拒绝：无法足够可靠地确定当前浏览器 URL。已停止 UI 操作；不将工具拒绝写成产品故障。用户可在现有 Dashboard 刷新后核对版本/状态与上述结果，页面实看仍待核验。

## 回滚与遗留

Alpha 4 的稳定发布前基线 `2f6f27b`、实验检查点和已验证备份均保留。若 Backend/API、采集协议或数据库检查失败，优先回滚运行代码，不用旧备份覆盖新采集数据。此次未发生回滚。

GitHub 上传故障已解决。GitHub 专用代理只保存在本仓库的 Git 配置，日后本机代理端口或运行状态改变时需重新验证；无需修改应用代码。仅文档与标签收尾不重新启动服务或重复花费模型调用。

干净检出与基线检查 worktree 已移除。隔离 HTTP 冒烟目录 `runtime/worktrees/p0-stability-release-20260928/_tmp/alpha5-http-smoke/` 和迁移验证副本 `runtime/worktrees/p0-stability-release-20260928/runtime/p0-migration-copy.db`（含 SQLite `-wal`/`-shm` 伴随文件）仍是 Git 忽略的本地临时文件，未被程序依赖、未进入提交；本环境安全策略拒绝了针对这些精确路径的文件删除操作，因此留待后续清理，不影响生产数据库或运行服务。

剩余限制仅为页面视觉核验待完成及上述保留的临时验证副本；不继续扩展实验、日期轨或通知功能。
