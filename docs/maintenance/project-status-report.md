# CRR 项目阶段与功能现状报告

## 当前专项验收状态（2026-10-07）

**Prediction Review Ledger v1：`READY_FOR_ACCEPTANCE`（本地与 CI 实现验收完成；开发 PR #10 的三项 checks 已通过）。** 当前唯一验收报告为[Prediction Review Ledger v1 验收报告](prediction-review-ledger-v1-report.md)；此状态不是生产迁移、上线或发布批准。

- 开发分支/源码基线：`codex/prediction-ledger-v1-20261007` / `1e865c37d1643f429162adeb0fab61bb7371a47b`（基线别称）。源码提交 `4f9951f2d938e5ea30aa38ab20ec5160f8b6ee50`、纯 EOF 格式提交 `48c3b3d7e3305b86f84a912c66ef3b8e98eee3a0` 与初次七文档提交 `65ce2c71931d3c82d8f662c7953949be48bb92ce` 已在开发分支；65ce 已 push，PR [#10](https://github.com/Oblivionis-ling/codex-reset-radar/pull/10) 已创建。对应 [Actions run #35](https://github.com/Oblivionis-ling/codex-reset-radar/actions/runs/37545840791) 对 head 65ce completed/success，backend/web/collector-extension 三项 checks 全通过。格式映射回执：`runtime/review/ledger-v1-20261007/git-eof-format-receipt-20261007-01.json`。
- 独立 Schema 7→8 candidate 验收已通过；Web/Collector 六条 npm 命令 exit 0；真实存量 24h 小包校验通过，legacy provenance 缺口保留。证据均位于事项 `runtime/review/ledger-v1-20261007/`。
- 最终 clean 源码 Backend 全量 `140 passed, 1 StarletteDeprecationWarning, 177.97s, exit 0`；B 同轮 Web 7、Collector 18，六条 npm test/typecheck/build 均 exit 0。empty-API smoke retry exit 0、health/radar 200、网络与 SMTP blocked。CLI smoke 前后数据库主文件 hash 不变；源码 SHA 由 clean source manifest 单独核验。Receipt/stdout 在 `runtime/review/ledger-v1-20261007/clean-final-20261007T060513118-fefce178/steps/`。
- C 的 formal focused `3 passed in 27.04s` 与前版 worktree Backend `138 passed in 175.38s` 均早于 no-clobber 修复，仅作为前版证据保留；最终 clean Backend 140 已覆盖修复源码。Synthetic ZIP 最新 verifier 为 valid/reference verified、SYNTHETIC 208、unknown 0；220 个 manifest 对象中含 12 个 placeholder input snapshots，故 208 是排除占位符后的 provenance 对象数。attempts 43 是合并计数：22 record_type=attempt（MockTransport 合成 request/response，不访问真实网络）+21 record_type=run_lifecycle；DTO 未单列 transport.kind，不把 43 全称为真实 HTTP。
- 生产 `/api/v2/health` 与 Web 5173 仅只读 HTTP smoke；Backend 仍启用 intelligence。此事项未主动调用模型/通知、未写生产数据、未启停服务；自然后台活动不计入主动调用。
- 主 checkout 为 `main`/HEAD `1e865c37d1643f429162adeb0fab61bb7371a47b`，tracked/staged 均为 0，原 10 个 untracked 路径保留。最终只读观察 receipt `runtime/review/ledger-v1-20261007/final-readonly-observation-20261007.json` SHA256 `2EBAD6091EF682F0E29D10124A6D62604EAA5A897AC7C7FB601789FD3DA670C0`：Backend health 与 Web 首页/proxy 200、Alpha5、三个采集监视器 healthy、latest Judge 930/VALID，Schema 7 snapshot hash 不变；本轮仅 GET，无主动模型/通知/生产写入/服务启停，后台自然活动单独记录。七文档初次提交及 PR #10/CI 已同步通过；本次两文档 metadata 收口由 A 后续单独同步并复验。
- A 最终只读 receipt `runtime/review/ledger-v1-20261007/core-size-estimate-20261007-01.json`：synthetic DB 1,085,440 B，ledger 210 rows / 179,277 payload B、artifacts 129 / 311,434 B；新对象 dbstat 794,624 B，空 Schema 8 的 dbstat 基线 49,152 B，净 745,472 B；integrity OK、FK 0、hash 不变。按 63/day 的 legacy persisted-Judge proxy、365 天并以 6 个 output_committed 线性缩放，规划估算约 1.88 GB payload 与 2.86 GB 分配页/年；不是一年实测、HTTP 频率或容量/准确率保证，未知项见专项报告。
- A 最终 real ZIP CLI verify exit 0、9 hashes/reference valid，原 ZIP SHA256 未变；窗口和 freeze 为 2026-10-05T18:24:18.928585Z 至 2026-10-06T18:24:18.928585Z（freeze 等于 source capture）。legacy body 441、parent version 369、Normal history 1 缺口保留；provenance 是 `LEGACY_UNDECLARED`，没有伪造现代 runtime identity。
- Schema 7→8 candidate 迁移与旧 baseline 读取 Schema 8 均通过。当前 Ledger v1 范围包含正式 pipeline 持久链、append-only truth、Normal compatibility projection、脱敏自包含包与 verify CLI；独立 Banked 预测、三线 UI、正式评分及自动通知仍未实施。操作说明在 `docs/v2/prediction-review-operations.md`；唯一验收报告在 `docs/maintenance/prediction-review-ledger-v1-report.md`。
- 本事项未主动调用真实模型/通知、未写生产数据、未启停服务；生产 Backend 的自然后台活动单独记录（只读观察曾显示 intelligence enabled，不计为本事项主动调用）。主 checkout tracked/staged 状态未变、10 个原始 untracked 文件保留；开发分支源码、格式与初次七文档提交均已完成并 push。
- 当前本地与 CI 实现验收均为 `READY_FOR_ACCEPTANCE`；PR #10 的 backend/web/collector-extension checks 与 Actions run #35 已成功。A 将单独提交/推送本次两文档 metadata 收口并核验最终 CI；生产未部署。禁止 main merge、tag、deploy；生产迁移或启用另需用户确认。

以下既有项目现状正文保持原样，描述的是其报告日期 `2026-10-04` 的历史快照，不应覆盖本节较新的专项状态。

报告日期：2026-10-04，时区 `Asia/Shanghai`。
运行事实截止：2026-10-04 02:17–02:20；本报告不是持续监控结果。
源码基线：`main / af3cde32aa4c9f7f6d58973535f39445fb4d71c5`；远端为 `https://github.com/Oblivionis-ling/codex-reset-radar.git`，`v2.0.0-alpha.5` 指向该提交，Git 网络与权限可用。

当前是可运行的单用户信息雷达 Alpha5；Full 与 Banked 双类型日期产品规范已完成，核心增强与准确率验证仍待实施。它不是已验收的付费预测服务。

本报告回答项目走到哪一步、现有哪些功能、哪些证据已取得，以及接下来应做什么。现有规范以[日期预测与复盘规范](../v2/prediction-and-review-spec.md)为唯一实施目标入口，不能把设计字段写成已上线能力。

## 1 阶段与用户目标

| 阶段 | 已有结论 | 边界 |
| --- | --- | --- |
| 已完成的骨干 | 本地采集、持久任务、分析翻译、事件周期、Judge 与 Dashboard；Alpha5 P0 正式合入 | 功能存在不是全部语义或准确率通过 |
| 当前阶段 | 语料审核已收尾，日常增量运行；日期预测、长期复盘和评价规格已形成 | 不新开全库审核或重跑，不恢复旧实验 |
| 待实施阶段 | 双对象结构化日期、长期日志、脱敏导出、固定集评分、真实通知验收 | 商业订阅、多用户分发和服务保证后做 |

已确认的产品规则与当前实现必须分开：

- 近期供用户个人使用；未来付费消息分发中，日期预测与信息分发同等重要。
- Extra Full 与 Banked 分别预测实际执行、实际发放开始；不是公告时间、观察代理或个人到账时间。
- Normal 是最近确认实际 Full 加七天的周额度参考；中途实际 Full 重算，Banked 不推进或重置 Full 钟。
- 七天是用户基线，未核实为所有账号政策；到期不等于观测恢复，不制造额外 Full，不自动滚动旧基线。
- 实质新信息触发新预测，重复 sighting 不重算；缺依据的 Extra Full/Banked 保持未知，与 Normal 分开。
- Full/Banked 分别以 ±24h 为主、±48h 为辅助；无固定最低提前量，保留首次、末次事前和全部中间版本。
- 事后更新按通报评价，不计预测命中；保留日期/范围精度，缺可信真值时未判定，不补造分钟。
- 用户自行定期用 ChatGPT 复盘，CRR 准备可追溯脱敏资料，不自动调用高阶模型、增加预算或上线调参。

2026-09-30 P0 报告将周实验关闭为 `CLOSED_NOT_ADOPTED`；A1/B1 未采纳，Laya 不是生产默认。`scripts/replay_corpus_pipeline.py` 是隔离语料回放，不是线上周预测；正式链仍为 DeepSeek。语料阶段已结项，不重开全库审核或恢复旧调用预算；正式源码没有 `apps/laya-worker`。

## 2 正式骨干与功能矩阵

```text
X Profile / Replies / Search → 扩展采集 → SQLite 持久任务 → 内容政策与父帖
→ DeepSeek 分析/翻译 → 事件、Full 周期与案例检索 → Judge 输入版本/健康保护
→ localhost API → TypeScript / Vite Dashboard
```

“源码存在”表示有真实实现；“本次可达”仅限本次 GET/元数据观察；未主动走过的分支仍需隔离或受控实测。

| 功能 | 真实源码入口与 symbols | 本轮证据与限制 |
| --- | --- | --- |
| 三路采集与上下文 | 扩展 [content.ts](../../apps/collector-extension/src/content.ts)、[parser.ts](../../apps/collector-extension/src/parser.ts)、[background.ts](../../apps/collector-extension/src/background.ts)；reply-context 与 Backend [reply_context.py](../../apps/backend/app/reply_context.py) | Profile/Replies/Search 采集及父帖祖先补全已实现；三路心跳本次可达，未做浏览器实测 |
| 持久任务与 pipeline | [db.py](../../apps/backend/app/db.py) `enqueue_post/recover_jobs/claim_post_job/finish_job/fail_job`；[pipeline.py](../../apps/backend/app/pipeline.py) `identity/_worker/_process_post/request_judge` | SQLite 持久任务、去重、RUNNING 恢复、有限重试、缓存和 Judge single-flight 合并已实现；异常分支待隔离验证 |
| 分析、翻译与内容政策 | [intelligence.py](../../apps/backend/app/intelligence.py)、[deepseek.py](../../apps/backend/app/deepseek.py)；db `content_policy/content_use_allowed` | DeepSeek 分析/翻译及按内容版本限制分析、事件晋升、Judge 和案例用途已实现；本轮未调用模型 |
| 事件、周期与预告 | [db.py](../../apps/backend/app/db.py) `upsert_reset_event/upsert_candidate/_rebuild_cycles/special_announcements/next_reset_baseline` | Full/Special 与候选分流，只有 Full 开周期，Banked 是 Special 子型；`scheduled_at` 是明确预告文本，不代表已执行事件或独立 Banked 预测；七天基线过期不滚动 |
| 检索、输入快照与 Judge | db `retrieve_historical_cases/judgement_context/refresh_input_snapshot/validate_judgement`；[pipeline.py](../../apps/backend/app/pipeline.py) `IntelligencePipeline._run_judge` | 有界案例和版本快照已实现；输入变化拒收，并校验有效期、周期、政策、健康；本次结果 VALID |
| 采集新鲜度 | [collector_health.py](../../apps/backend/app/collector_health.py) `collector_health` | 15分钟窗口、未来时钟及不健康状态校验；本次 HEALTHY 不证明来源完备 |
| API 与 Dashboard | Backend [main.py](../../apps/backend/app/main.py) `create_app/health/radar/radar_payload`；Web [api.ts](../../apps/web/src/api.ts)、[main.ts](../../apps/web/src/main.ts) | FastAPI 与 TypeScript/Vite（不是 React）；health、radar、首页及代理本次均200，未做浏览器视觉验收 |
| 独立本地启停 | [start-v2-local.ps1](../../scripts/start-v2-local.ps1) `Get-RecordedProcess/Save-ProcessRecord`；[stop-v2-local.ps1](../../scripts/stop-v2-local.ps1) `Stop-RecordedProcess`；[common-v2.ps1](../../scripts/common-v2.ps1) `Start-CrrDetachedProcess` | 项目归属核验与 WMI 脱离启动存在；本轮只验证记录，不执行启停 |
| 语料导出与日志 | [corpus_standard.py](../../apps/backend/app/corpus_standard.py) `export_package`；[logging_runtime.py](../../apps/backend/app/logging_runtime.py) `RuntimeLog.write/_prune` | 已有 JSONL/manifest 底座及诊断日志；预测复盘包与长期账本待补 |

启动不依赖 Codex 聊天窗口存活，但不是24/7服务、开机自启或崩溃守护；登录退出、重启和浏览器运行仍有各自限制。

## 3 本次实际运行快照

下列时间均为 Asia/Shanghai；health 于02:19、radar/代理于02:20观察。不同请求不是原子快照，不据此证明长时稳定。

| 身份或运行项 | 本次结果 | 证据限制 |
| --- | --- | --- |
| 应用版本 | `2.0.0-alpha.5` | API 返回的当前版本 |
| 已加载模块指纹 | `a178cd390dfb1077`，与磁盘同一组六模块一致 | 仅覆盖 main/db/pipeline/intelligence/reply_context/collector_health |
| health.commit | `af3cde32aa4c9f7f6d58973535f39445fb4d71c5` | [runtime_commit](../../apps/backend/app/version.py) 现读 HEAD；不能证明内存载入完整提交 |
| 模型与 Judge Prompt | `deepseek-v4-flash`；`v2-reset-judge-8-context-health` | API 声明；未提供已加载 Prompt 哈希，不借历史哈希替代 |
| Backend | PID18612，9月30日16:12:38启动，127.0.0.1:8787 | 根目录、可执行文件、命令标记、启动时间及监听归属匹配 |
| Web | PID6488，9月30日16:12:44启动，127.0.0.1:5173 | 同上；未操作或重新加载进程 |
| 可达性 | Backend health/radar、Web首页及radar代理均200 | 只读 HTTP smoke；不是视觉或商业交付验收 |
| 调度 | pipeline/Judge ready，待处理任务0 | 仅该健康快照，不推断后续请求数 |

| 采集路 | 最后心跳 | 年龄秒 | 状态 |
| --- | --- | --- | --- |
| Profile | 10月4日02:18:30.185 | 37.2 | healthy / FRESH |
| Replies | 10月4日02:18:29.987 | 37.4 | healthy / FRESH |
| Search | 10月4日02:18:40.950309 | 26.5 | healthy / FRESH |

Judge #735：判断时刻02:13:24.446941，完成02:13:30.817215，有效至04:13:24.446941；`VALID/current/ready`，判断时与当前数据健康均 `HEALTHY`，后端与代理返回同一 Judge。

主等级及24/48/72h为 `GREEN/GREEN/GREEN/YELLOW`，仅记录该结果，不作为准确率或验收门槛。本次未另外提取日期起止及依据，不补造该快照的日期值。

该健康快照有549帖、16正式事件、14候选、735 Judge；API未提供周期总数，未查DB补数。特殊事件视图3条、预告视图0条只是返回窗口，不等于总量。

Normal 为 `expired`，基线2026-09-19 16:09:17；API最近 Full 记录时间2026-09-12 16:09:17，`time_basis=post_time_proxy`。两者均不能称为独立实测执行开始，也不能据此声称已恢复或没有后续事件。

本轮 GET 没有触发业务恢复、手工 Judge 或心跳。日常后台仍独立运行；本轮未发起模型/通知，不把自然后台活动写成全系统调用为零。

## 4 通知能力与交付边界

[registry.py](../../apps/backend/app/notifications/registry.py) 的 `CHANNELS/build_adapter` 与 [adapters.py](../../apps/backend/app/notifications/adapters.py) 包含 PushPlus、WPush、Server酱Turbo、IYUU、WxPusher、ShowDoc；[email.py](../../apps/backend/app/notifications/email.py) 有 `SmtpEmailAdapter`。PushPlus/WPush 的 ClawBot 变体复用相同适配器。

[service.py](../../apps/backend/app/notifications/service.py) 的 `NotificationDispatcher.send_once/settle/send_with_email_fallback` 提供单次发送、支持查询渠道的有限状态查询，以及失败或未确认时的显式邮件兜底。

[ledger.py](../../apps/backend/app/notifications/ledger.py) 的 `NotificationLedger.reserve/record/recent` 使用独立本地账本去重、记状态和查询；不是商业用户投递系统，也没有本轮交付实测。

[scripts/test_notifications.py](../../scripts/test_notifications.py) 有统一发送脚本与离线 `selftest`；真实发送要求显式 `--live` 和交互确认。本轮发送0，未执行 CLI 或读取通知凭据；这不表示历史手动测试均为0。

main/pipeline 未接自动发送钩子；[人工接收验收表](../notifications/testing-guide.md)没有手机或邮箱收件验收证据。mock、渠道接受和 SMTP 接受不能冒称 `DELIVERED` 或收件箱送达。

## 5 关键缺口和未承诺事项

| 缺口 | 当前已有底座 | 尚未完成 |
| --- | --- | --- |
| 独立双对象日期 | Judge 的 Full 24/48/72h 与可选 estimated_start/end/basis | 独立 Banked 预测、三条线版本结构；颜色不是日期准确率 |
| 预告与真实开始 | special_announcements 可抽取明确 scheduled_at | 预告不是预测推断或正式完成，不代替真值 |
| 预测时间与历史 | Judge 历史、input_versions/input snapshots | 每目标全部版本、attempt、真实 output_available_at 与失败/拒收链 |
| 真值修订 | 正式事件、范围、time_basis 与证据引用 | 长期 append-only truth revisions、独立精度审核及可靠目标关联 |
| 用户离线复盘 | 语料 export_package、版本摘要、去敏函数 | 完整预测脱敏复盘包；白名单、secret URL、私人信息/私有推理排除 |
| 留存与评分 | RuntimeLog 默认五天；现有有效性校验 | 独立长期账本、固定事件集24/48h评分；不能靠轮转日志唯一留存 |
| 准确率与商业化 | 单用户运行与初版评价规范 | 准确率实证、最低命中率或服务保证、多人付费分发均未验收 |
| 新信息源与模型 | 当前 Tibo/DeepSeek 正式链 | 新模型发布、故障/补偿等只作待验证理论，不写死事件或升色 |

## 6 检查证据与后续优先级

| 证据类别 | 本次可引用结果 | 不能替代什么 |
| --- | --- | --- |
| 源码核查 | 本报告列出的真实文件与 symbols，基线 af3cde32 | 不能证明每条分支本轮执行或语义正确 |
| 运行快照 | 10月4日02:17–02:20进程、GET、心跳及 Judge 元数据 | 不能证明视觉、24/7可靠性、日期命中或通知收件 |
| 历史测试 | [P0报告](p0-stability-release-report.md)记录44隔离、94 Backend、7 Web、18 Collector通过及前端类型/构建通过 | 9月30日历史记录，不是本轮新回归 |
| 历史 GitHub CI | [CI run 36689843405](https://github.com/Oblivionis-ling/codex-reset-radar/actions/runs/36689843405)，上述 HEAD，9月30日 success | 尚未提交的新文档或新功能没有本轮 CI 结果 |

本轮只做 GET 与文档检查，未运行 Backend/Web/Collector 测试、类型检查、构建、模型业务回归或通知实测。所有日期、导出、长期日志与评分新增能力仍待验收；文档检查不写成业务 PASS。

后续最多三步，均需后续技术实施授权：

1. 先复用正式链补长期日志、实际尝试/输出时间、运行身份与真值修订，以及可追溯脱敏导出；保留现有契约和历史。
2. 再分离 Normal/Extra Full/Banked，实现 Full/Banked 结构化预测及固定集评分，保留未知、首末和全部中间版本；不另建核查模型或全库重跑。
3. 最后隔离回归与受控验证，用户确认后上线；通知另选单渠道，由用户人工授权真实实测。业务 HTTP/模型预算须另明确，不复用旧预算或流程答复。

## 7 GitHub 同步范围与回执

官方仓库：[Oblivionis-ling/codex-reset-radar](https://github.com/Oblivionis-ling/codex-reset-radar)。远端 `main` 与源码基线一致，现存 Alpha5 标签仍指该基线；Git 网络与权限可用。仅更新文档不创建新 Alpha，也不移动旧标签。

CI 检查 Backend/Web/Collector，不负责部署。本轮只更新报告和索引，未暂存、提交或推送；推送后的 CI 结果以实际回执记录，不在本报告预写同步 commit 或自指 SHA。

六文件待提交白名单：[本报告](project-status-report.md)、[文档导航](../README.md)、[产品模型](../v2/product-model.md)、[数据模型](../v2/data-model.md)、[API 契约](../v2/api-contract.md)、[日期预测与复盘规范](../v2/prediction-and-review-spec.md)。后四份是已审文档，本轮不修改。

九份未跟踪任务/样本材料及 ignored runtime、raw corpus、DB、运行日志、凭据和临时资产均不提交；本报告不依赖这些本地材料，也不包含真实语料或模型请求。

日常运行边界见[本地运行](../v2/local-development.md)；历史原稿与旧快照不覆盖。
