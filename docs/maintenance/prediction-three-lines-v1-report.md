## 受控模型验收（2026-10-09；本轮结果已定稿；Git同步以 controlled-model-test-v1/git-final-01/receipt.json 为准）

S3 正式 N=0 评分已执行：导出/评分 freeze_at 为 2026-10-09T10:02:41Z，评分窗口为 [2026-10-09T09:00:00Z, 2026-10-09T10:02:41Z)。16 个 panels 的 N 均为 0，比例均为 null/不可计算。四个文件实际路径分别为 validation-01/s3-no-independent-truth-definition.json、validation-01/s3-no-independent-truth-set.json、validation-01/s3-no-independent-truth-assessment.json、validation-01/s3-no-independent-truth-final-only.json。只有 assessment.json 与 final-only.json 两个文件各为 10,429 bytes，SHA256 均为 54ef4e98c84663c51462701b5c6c1947081983be5feaecbfbda19d6daa35e8dd 且字节相等；不将此文件哈希归给 definition 或 set。scored 包 s3-review-03-scored.zip 为 29,513 bytes、SHA256 237285da0504a08881c2bfad1bde5dbb755e9b853c09325c1d8c39d55d409c10，verify exit 0、valid=true、10 个包内文件哈希通过、assessment reproduced 1。该 N=0 结果不是 100% 预测准确率或 model quality pass；准确率仍为 NOT_EVALUATED。

当前分层结论：受控语义 PARTIAL；实际预测准确率 NOT_EVALUATED；部署 NOT_DEPLOYED。既有 Backend 318 离线通过证据复用有效；本轮未改源代码或冻结 Prompt，且发现两项新的 API/UI 状态映射缺口，修复前不进入发布审查。本轮 11/13 个预算 HTTP 已全部终态，无新增模型调用；S4 缓存精确复用闸未通过、cache_reuse=0，故 0 HTTP。请求声明模型 deepseek-v4-flash，响应标识 deepseek-flash；冻结 Prompt 标识为 v2-post-semantics-9-context、v2-zh-translation-2-context、v2-reset-judge-9-two-targets。code manifest 身份摘要 1c7a29ad5c561c240e5ce6b67e59cf4eb68d213e3c42160e260769acce58a3df，运行 HEAD 547f2b43c72bd0e61f9fb0f30d72bfafdb0ff0b4。

根 .env 未设置 DEEPSEEK_TIMEOUT_SECONDS，正式 config.py fallback 为 45 秒；S1 的 45 秒 Judge timeout 与正式 fallback 一致，不据此自动延长。场景来源按冻结 index：S1/S3 为 synthetic；S2/S4 为 acquired 真实文本，provenance 均 legacy undeclared。

Judge 时点、请求 freeze 与导出/评分 freeze 分开记录：S1 judge_as_of=2026-10-09T09:16:27.312224Z，依据 request-0003.user 的 JSON 后缀 context.judged_at，body hash 前缀 8030…；S1 request freeze=2026-10-09T09:16:27.625Z，不替代 judge_as_of。原 manifest 与 live-terminal 的 as_of/runtime=null 保留为 runner 记录缺口，不代表实际 judge_as_of 无法还原。S2 judge_as_of=2026-10-09T09:39:25.694096Z，S3 judge_as_of=2026-10-09T09:40:18.629816Z；10:02:41Z 是 export/score freeze_at，不是任何场景的 Judge as_of。当时可见输入：S1 synthetic future FULL_RESET 为 2026-10-10T15:00:00Z UTC、Full 范围 all_paid；Banked 无独立信号，本场 Judge 未返回，不可推出 Banked 结果。S2 为当前 Loading 发放/传播中，posted_at 2026-10-07T19:19:17Z，post_time_proxy 不能当独立真值，nextTomorrow 无法绑定日期；S3 synthetic 早期轮次延期后完成的文本时间为 2026-10-08T17:00Z，另有 scope unknown 的独立 NEXT Full 2026-10-11T15:00Z；S4 是普通回复，正文 content hash 与 metadata 匹配，但完整实际请求和模型参数证明不足，未通过精确复用闸 1。

计数边界：11 HTTP = analysis 4 / translation 4 / Judge 3；按场景 S1=3、S2=3、S3=5、S4=0。2 个 Judge 收到成功 JSON，1 个 Judge timeout。成功 Judge 共返回 4 个原生目标项：S2 Full/Banked 与 S3 Banked 共 3 个合法 UNKNOWN；S3 Full 1 项正式拒收 OFFICIAL_PLAN_NOT_VERIFIED，不是第四个 UNKNOWN。S1 没有最终模型 target，S4 本轮没有 target。S1、S2、S3 各有 2 条 question forecast_version（共 6 条问题版本，不等于 6 个已接受预测）；共享 Judge output_committed 行仅 S2、S3 各 1、合计 2。每场的 attempts/forecasts/inputs/outputs/evidence/identities/truth revisions 是独立 DTO 计数，不由 HTTP 推算；S3 的 5 outputs 是 output DTO，不是 5 次 Judge。scene state 与语义判定分列，S3 HTTP/Judge 成功不等于场景全通过。

DB/API readback：S1 events 0 / cycles 0 / candidates 1 / Ledger rows 22；S2 SPECIAL_RESET/BANKED 1 / Full 0 / cycles 0 / candidates 0 / Ledger rows 29；S3 events 0 / cycles 0 / candidates 1 / Ledger rows 44。S2 truth_revision 1 是模型生成的 post_time_proxy，不是独立评分真值。

Reader / 安全 DTO 计数（来源为 validation receipt 与已验证包；与 HTTP 次数分列）：

| 场景 | HTTP | 活动根/Ledger rows | attempt DTOs | question forecast versions | input DTOs | output DTOs | evidence DTOs | runtime identities | truth revisions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| S1 | 3 | 22 | 6 | 2 | 15 | 2 | 7 | 2 | 0 |
| S2 | 3 | 29 | 6 | 2 | 15 | 3 | 8 | 2 | 1（post_time_proxy，非独立真值） |
| S3 | 5 | 44 | 10 | 2 | 23 | 5（不是 Judge 数） | 14 | 2 | 0 |
| S4 | 0 | 未运行 | 未运行 | 未运行 | 未运行 | 未运行 | 未运行 | 未运行 | 未运行 |

- **S1：** scene state FAILED_TERMINAL；来源 synthetic。analysis、translation 均 HTTP 200，Judge 45 秒 timeout 且 Ledger 有 timeout 记录，受控语义 FAIL。实际 judge_as_of=2026-10-09T09:16:27.312224Z，来自 request-0003.user JSON 后缀 context.judged_at（body hash 前缀 8030…）；request freeze=09:16:27.625Z，二者不可互换。原 manifest/live-terminal 的 as_of/runtime=null 是 runner 记录缺口，不代表真实 as-of 不可还原。S1 只有未来 FULL_RESET、UTC 2026-10-10T15:00:00Z、Full 范围 all_paid；Banked 无独立信号且本场 Judge 未返回，不能推出 Banked 结果。正式 API 却把 Full/Banked 两 target 标成 not_implemented、reason LEGACY_TARGET_NOT_IMPLEMENTED。Normal 不是模型 target；无可信 Full anchor 时规则仍可读，不需要 Judge 成功。events 0 / cycles 0 / candidates 1 / Ledger rows 22。
- **S2：** scene state COMPLETED；来源 acquired 真实文本，provenance legacy undeclared。材料为当前 Loading 发放/传播中，posted_at 2026-10-07T19:19:17Z；不是未来下一次发卡计划。标题“Banked计划”不作事实，SeeYouTomorrow/nextTomorrow 不能绑定下一次发卡日期。Judge as_of 为 2026-10-09T09:39:25.694096Z。正式 API 为 Full UNKNOWN_VALID、Banked UNKNOWN_VALID/all_paid，两条 history 各 1 项。S2/resets 有 1 项 SPECIAL_RESET/BANKED，Full 0 / cycles 0 / candidates 0 / Ledger rows 29。场景语义有限 PASS：Banked 不冒充 Full、周期正常，next 无依据则保留 UNKNOWN。truth_revision 1 是模型生成的 post_time_proxy，不是独立评分真值。
- **S3：** scene state COMPLETED；来源 synthetic，受控语义 PARTIAL。Judge as_of 为 2026-10-09T09:40:18.629816Z。synthetic 早期延期后完成文本提到 2026-10-08T17:00Z；另有 scope unknown 的独立 NEXT Full 2026-10-11T15:00Z。S3 Full history 确有 1 条拒收项，question ID 前缀 9b91…；rejected_output 中为 start_only/minute 且提到 Oct 11。Radar 当前 Full 的 forecast_id/form/dates 均为 null；该拒收原值只存在于 rejected_output，不能当作当前可信日期。明确 point/second 计划因此被正式 API 以 OFFICIAL_PLAN_NOT_VERIFIED 拒收；Banked 的合法 UNKNOWN 保留，history 1 项。post31 有 synthetic 对照标记且 scope unknown；不生成正式 Full/Normal anchor 是正确保护。延期后完成的文本只构成时序疑点，不是独立实际完成真值；未晋升事件本身不是错误。events 0 / cycles 0 / candidates 1 / Ledger rows 44。Judge/HTTP 成功不代表本场全通过。
- **S4：** scene state SKIPPED_HARD_GATE，语义 NOT_RUN；来源 acquired 真实文本，provenance legacy undeclared。普通回复的 cache content hash/metadata 匹配；因缺完整实际请求与模型参数证明，未通过精确复用闸 1，cache_reuse=0，故 0 HTTP、无 target；不是正文内容缺失或哈希不匹配。
- **页面与状态表达：** 主方通过 CUA 在新 IAB tab 3、http://127.0.0.1:15173 实看 S3 API 页面中的 Radar 三行，实际页面观察完成且功能状态可见；Banked history 1 项，展开共享目标 attempt 1 显示成功并输出 UNKNOWN，Full 的拒收历史与 Banked UNKNOWN 可区分。S3 Full history 有 1 条 rejected 项，但 Radar 当前 Full forecast_id/form/dates 均为 null，日期只在 rejected_output，不能作为当前可信日期。停止中的 Vite 视觉进程未独立捕获组件源码 root、工作目录及 build identity；现有证据仅到 R/source config import，因此不能称冻结 Web 视觉已完整验收。API 进程使用 bundled Python，与后续 fresh venv 不同；该运行身份限制不影响正式 R/source CLI/TestClient 模块及 318 项旧冻结测试身份。S1/S2/S3 的 Normal 均无可信 Full anchor/basis，结果不可计算；API not_backfilled 与 UI 固定文案“参考可计算但版本未回填”错误地暗示可计算，是同一状态映射缺口。截图仅在对话内联展示，未本地落盘，不提供 PNG 路径。
- **导出与隔离：** validation-01 receipt 记录：s1-review-01.zip 17,849 bytes，SHA256 be839a00c71ca03f86b908fba960808798bbf02f069bbb330906b2a73dedf447；s2-review-01.zip 22,796 bytes，SHA256 a41e085beeef515212a617d50582e5d86d4664372440eb7516bb73b2e93903ad；s3-review-02.zip base 26,549 bytes，SHA256 e86f36321b17b2792ec4a4cea58f5dc5d8dbbfc85c09b7e0eb10bf756ab10518；以上均 verify exit 0、valid=true、10 个包内文件哈希通过。S3 base 对应活动根 44 / high-water 44；44 是活动根数，不是 ZIP 内所有对象或 DTO 总数。S3 scored s3-review-03-scored.zip 29,513 bytes，SHA256 237285da0504a08881c2bfad1bde5dbb755e9b853c09325c1d8c39d55d409c10，verify exit 0、valid=true、10 个包内文件哈希通过、assessment reproduced 1。旧 s3-review.zip 因调用选择冻结 highwater 33 而为空，保留为范围选择错误，不算 exporter 通过证据，也不证明 exporter 故障。helper 已归档；本轮 _tmp recursive delete 被 executionPolicy 拒绝，原件保留且未绕过，旧 envprep 未删。验证期间克隆 API lifecycle 的 clonehash 变化不涉及生产或执行 source DB；测试服务已停止，生产未动。

建议最多三项：① 将明确 point/单边、精度与句子时序歧义列为后续 Prompt 校准任务；post31 synthetic、scope unknown 的未晋升事件不作实际完成真值，本轮不修改冻结 Prompt。② 合并修复 API/UI 状态映射：S1 现代 timeout 不得冒充 legacy not_implemented；Normal 无可信锚点时不可计算，须修正暗示“参考可计算”的状态文案。③ 有界补齐 S1 timeout、S4 精确缓存复用及 S3 API/Web 组件源码 root、工作目录和 build identity 绑定证据；UI 绑定补证不需要新模型调用，任何新增模型 HTTP 仍须另获授权。本轮结果已定稿；Git同步以 controlled-model-test-v1/git-final-01/receipt.json 为准。须合读 runtime/review/prediction-three-lines-v1-20261009/controlled-model-test-v1/validation-01/validation-receipt.json、runtime/review/prediction-three-lines-v1-20261009/controlled-model-test-v1/validation-01/validation-corrections-01.json 与 runtime/review/prediction-three-lines-v1-20261009/controlled-model-test-v1/validation-01/local-validation-services-identity-correction.json；原始 receipt 未修改。本节之后的既有章节保留为本轮真实模型验收前的历史快照，不改写其原始结论或证据。

# 三条日期线、双目标预测与固定集评分 v1 — 验收报告

最终结论（2026-10-09）：`READY_FOR_CONTROLLED_MODEL_TEST`。最终冻结 code manifest `1c7a29ad5c561c240e5ce6b67e59cf4eb68d213e3c42160e260769acce58a3df` 已通过离线验收：Backend 318 passed / 0 failed / 0 skipped，Web 17、Collector 18，类型检查与构建成功。e-clean-release-01 回执、C final05 样包/测量、D 隔离 UI 与 cleanup 回执齐全。真实模型 HTTP、Laya、通知、生产迁移及部署均为 0；模型语义与实际准确率 `NOT_EVALUATED`，部署 `NOT_DEPLOYED`。旧 candidate 309/4 仅为历史失败证据，原回执保留。规范第 7 节公式未改；命令见[操作指南](../v2/prediction-review-operations.md)，契约见[数据](../v2/data-model.md)、[API](../v2/api-contract.md)与[产品](../v2/product-model.md)。

## 四层状态

| 层次 | status | 实证与边界 |
| --- | --- | --- |
| 工程 | READY_FOR_CONTROLLED_MODEL_TEST | 最终 manifest `1c7a29ad…`：Backend 318 passed / 0 failed / 0 skipped，Web 17、Collector 18；类型/构建、空库 API/CLI、样包及隔离 UI 均有最终回执。 |
| 模型语义 | NOT_EVALUATED | Fake/Mock 的校验、时间与目标链有 focused/集成证据；没有真实模型响应，不称受控语义测试完成。 |
| 实际准确率 | NOT_EVALUATED | 真实 scored B 为 legacy Full/Banked 各 N=1 的无预测；没有可证明事前的现代预测/可信真值成绩。 |
| 部署 | NOT_DEPLOYED | 生产 Alpha5/main 不动，main merge/tag、生产迁移/启停/部署 0。 |

## 基线、依赖与保护

source：D:\work\20260828-CodexResetRadar\runtime\review\prediction-three-lines-v1-20261009\source；feature 分支 `codex/prediction-three-lines-v1-20261009` 的依赖基线为 `ef226ebe14cf45ad7af80af1b14d87e17638e355`（Ledger PR #10 的 head）。正式实现及六份文档已按显式白名单分5组提交；实现+六文档提交头为 `1893db2d05e1ac72682f45d870c6bcb547c1fae9`，对应冻结代码 manifest `1c7a29ad5c561c240e5ce6b67e59cf4eb68d213e3c42160e260769acce58a3df`。最终doc-only提交头与该head的CI以 `runtime/review/prediction-three-lines-v1-20261009/git-closeout-01/receipt.json` 为准。

主方已只读核实 [Ledger PR #10](https://github.com/Oblivionis-ling/codex-reset-radar/pull/10) 仍 OPEN/未合并，head `ef226ebe14cf45ad7af80af1b14d87e17638e355`、base main `1e865c37d1643f429162adeb0fab61bb7371a47b`。本轮草稿开发 [PR #11](https://github.com/Oblivionis-ling/codex-reset-radar/pull/11) 以 `codex/prediction-ledger-v1-20261007` 为 base 并依赖 #10。实现+六文档提交头 `1893db2d05e1ac72682f45d870c6bcb547c1fae9` 的 [CI run 37841210618](https://github.com/Oblivionis-ling/codex-reset-radar/actions/runs/37841210618) 中 backend、web、collector-extension 均 SUCCESS；最终doc-only提交头及其CI见机器回执。[CI run 37546895176](https://github.com/Oblivionis-ling/codex-reset-radar/actions/runs/37546895176) 三 success 和[Ledger 报告](prediction-review-ledger-v1-report.md) Backend140/Web7/Collector18 仅属旧基线，不计本轮成绩。

生产 Alpha5/main 的原 Backend/Web 进程及 11 个用户 untracked 保留。startup-protection.json 是启动时点健康/三路 healthy 证据，不是新代码部署或持续健康证明。E 后验收检查 14 项保护资产（含11个用户文件）及本轮快照 SHA 均 matches=true。检查器已修为保留精度的 UTC ticks 比较，Backend/Web 同 PID/启动时刻，same_start 均 true；新证据为 e-clean-candidate-01/post-docs-02-protection-recheck.json。旧 false 为机器转换假阴性，原回执保留，不解释为服务变动。

所有机器证据位于 D:\work\20260828-CodexResetRadar\runtime\review\prediction-three-lines-v1-20261009。报告不嵌入正文、秘密、raw request/response。

## 历史 candidate 干净源码身份与范围（仅历史证据）

e-clean-candidate-01/candidate-identity.json：全文件 254，code/test/config 清单 106；明确包含 tracked working-tree diff、9 个新增正式源码/测试/CLI（在原8项之外新增 test_three_line_pipeline.py）及唯一新报告。main 的 11 个用户原件不纳入。source 前/后/copy SHA 三方相同；不复制 .git、实际 .env、ignored DB/ZIP、旧实验/运行资产或源 node_modules。

- code manifest SHA：393f0ac9af7f87e699103cf9dca4c783745aaf57b430d47749b080fc9262aef0。
- 全文件 SHA：7f717054f1363afaef6d0f5c213cfb0e112e8deb97bed3d8d08cad5deacc85b6。
- 哈希定义/逐文件 bytes/SHA/正式白名单在同目录 manifest；文档单独清单，后续 E 文档收口不冒充全文件身份未变。
- clean copy 在事项 _tmp/e-candidate-01-20261009-194a0a2b/source；匹配 requirements/package/lock SHA 后复用已安装的 fresh venv 和两套 npm ci 依赖。单元测试不依赖 ignored 真实包/旧实验或临时业务模块。临时 helper 只提供命令、防护、smoke/审计，不替代正式源码。

该 candidate 曾发现源码后续变化，且 Backend 309 passed / 4 failed。此段只保留对应轮次的输入身份与历史结果；最终代码身份和验收结果以本报告开头的 code manifest 为准，旧失败不改写为通过。

## 历史 candidate 实际执行结果（仅历史证据）

| 项目 | 结果 | 回执 |
| --- | --- | --- |
| Backend 全量 | exit 1；309 passed / 4 failed / 1 warning，pytest 277.86s，进程 279.0247679s。 | backend-full/result.json、stdout/stderr、backend-full-junit.xml |
| Web | test 17 passed，typecheck/build exit 0。 | web-test-02、web-typecheck-02、web-build-02 |
| Collector | test 18 passed，typecheck/build exit 0。 | collector-test-03、collector-typecheck-02、collector-build-02 |
| 空库 API/CLI | exit 0；Schema 1–8/22表、integrity ok/FK0，DB SHA 前后相同；final-only assessment 字节一致。 | empty-smoke-artifacts-02/receipt.json |
| 真实 scored B coverage | exit 0；2 parts、362 roots、assessment reproduced1、ref/valid true。 | sample-b-coverage-verify |
| base-v2 / 旧 v1 兼容 | 两项 exit 0；base 2parts/362roots/assessment0；v1 9hash/ref/valid、assessment0。 | base-v2-coverage-verify、legacy-v1-verify |
| Git/安全/大文件（本次范围） | tracked diff-check 0；2项扫描命中已明确裁定为显式测试假值/脱敏诱饵，requires_context_review=false、真实凭据false、未决0；无>5MiB、DB/ZIP/.env混入。 | post-docs-02-git-diff-check、post-docs-02-source-security-and-size-audit、post-docs-02-secret-context-decisions |
| UI 实看 | D final receipt 记录 Sol 主代理检查 formal06 clone、7 项 history 和 UI 语义；非用户人工验收，截图未落盘。隔离 API/Web PID 26376/23608 已停止，18787/15173 无监听；生产 8787 PID 18612、5173 PID 6488 保持。 | 已完成隔离 UI 检查；见 `runtime/review/prediction-three-lines-v1-20261009/d-api-web-visual-review-closeout-20261009.json` |

各路径均相对 e-clean-candidate-01。npm 首次六命令因 E 的 NODE_OPTIONS Windows 路径转义在启动前失败；修临时 helper 后新目录重跑。Collector 下一次因防护拦截 Vite localhost 查询失败；改为静态本地解析后 test-03 成功。空库首次 freeze 因 E 定义规则不是安全 token 返回 set_rule_required；修模板后全新空库/输出 -02 成功。失败全部保留，不覆盖、不归咎产品，也不排除正式测试。

本轮实际警告为 Starlette TestClient 使用 httpx 的弃用提示（建议 httpx2）；未为消警改 dependencies。依赖安装的 esbuild allow-scripts/whatwg-encoding 弃用警告保留，两边真实 build 已成功。版本为 Python3.12.14/Node24.18.0/npm11.16.0；fresh venv tzdata2026.5、pytest8.4.2、fastapi0.143.0、starlette1.7.0、pydantic2.14.0、httpx0.28.1。生产 venv 未补 tzdata；F 旧失败仍保留。

### 四个 Backend 失败及最小根因

failure-root-causes.json 与 expiry-isolated-diagnostic 为正式证据，没有改其他 owner 文件。

| 失败 | 根因/当前处理 |
| --- | --- |
| test_prediction_ledger.py:815 | REPOSITORY_ROOT 与 clean 根一致，失败只在强制 .git.exists；测试不便携，未制造假 .git。A 已改通用源码 marker，实际 root 断言保留。 |
| test_prediction_review_pipeline.py:681 | 旧总 forecast==1 假设单目标；保留 DB 的 RO 查询证实 Full/Banked 各1。A 已按每 target 身份/版本严格检查重复不增，共享 run/attempt、同事实 output revision 另核，不删除用例。 |
| test_three_line_pipeline.py:281 | 旧候选断言 radar["judgement"]，真实 API 是 flat judgement_id；C 修后 formal-three-line-06 实际 1passed/exit0，19.27s，但不是旧 candidate 通过。 |
| test_v2_contract.py:176 | legacy scalar 未声明精度自动 start_only，upper=None，Jan1+7 一直 baseline。全新进程单独重现 1failed/0.09s，排除前例 clock 泄漏。A 修共享 helper 的兼容 reference expiry，不补另一端、不升级 point。 |

候选失败永久保留；owner 修正不是重标旧 PASS，最终重冻结后全套再验收。现在不豁免 Expired、不只复跑个别测试。

## owner focused：独立于 clean 结果

- A core-clean-integration-01/implementation-ready-02.json：56passed/61.34s/exit0，含 F30、旧正式链、clean-root 和 expiry 回归，四项最新源码/测试 SHA 已与当前 source 相同；旧72/12 focused和失败仍保留，不计作全量。
- B scoring-focused-20261009-10/ready-receipt.json：79passed/exit0；missing output / origin冲突 P1 已回归。正式 synthetic 最终包 assessment reproduced1、final-only score 字节一致，CLI全 exit0；不覆盖最新 producer 全量证明。
- F time-contract-focused-f-20261009/manifest-fresh-e.json：30passed/exit0，fresh venv tzdata2026.5；原生产 venv 缺tzdata的失败留存。共享 helper 后续变化须最终回归。
- C c-code-ready-01.json：export-foundation-11 为67passed/18.09s，formal-three-line-07 为1passed/20.57s，均exit0。样本 A 已重建为 synthetic-formal-sample-v2-02：同轮全部4个 output、3个 forecast（含delay修订）纳入，NEXT/fresh 有明确排除。分类和=N与候选覆盖分别断言；这修的是样本定义遗漏，不是新增 scorer bug。旧66/正式06及失败保留，focused计数不相加冒充 Backend 全量。
- D d-api-web-code-ready-20261009.json：明确 code_frozen_for_e_final_suite，10项源码/测试 SHA 已核对；12项 API/Normal focused与 Web17/build是独立证据，实际 UI/截图仍由D收口。

## 三线、账本与时间契约

Normal 复用共享 Full+7 helper，method=null，参考非官方承诺，不进入 Full/Banked N；新锚点/历史版本和未回填/代理/精度保持区分。legacy scalar以 legacy_scalar_reference_only 处理参考到期，仍start_only/unknown precision/end=null；显式start_only仍upper_bound_unknown，不造执行上界。最终完整验收由 `runtime/review/prediction-three-lines-v1-20261009/e-clean-release-01/acceptance-summary.json` 记录，Backend 318/0/0。

Full/Banked 独立 target/date state/scope/时间形式/依据/版本，合法 UNKNOWN 不等于缺字段、拒收或 legacy 不支持。两个目标共享输入快照、父帖/必要祖先/事件来源、runtime identity、run/attempt；一个 HTTP 不按两个输出计两次。question version 与 target output revision 分开。

官方明确时间保护、真实 relative 原帖锚点/表达/时区、date envelope、单边保真、全局不可解析与目标级部分失败/共享输入迟到拒收均已由最终 producer/API 回归、样包和 UI 回执覆盖。最终 clean receipt 为 `runtime/review/prediction-three-lines-v1-20261009/e-clean-release-01/acceptance-summary.json`；D UI/cleanup receipt 为 `runtime/review/prediction-three-lines-v1-20261009/d-api-web-visual-review-closeout-20261009.json`。观察型可用时钟只为上界，拒收无产品可用时刻。

safe history getter 为 flat prediction-history-line-v1/安全 attempt DTO；首/末 boundary、total/source_output_count/truncated 与 append 顺序可见，不暴露 raw payload。append 首末不是评分事前首末证明。legacy source gaps 不造当时模型 UNKNOWN。

评分/附包绑定冻结集合、source/core collection identity、forecast/truth revision 和算法；新增 assessment 不改核心输入，不成 hash 环，不覆盖旧包/结果。candidate 空库 final-only 字节一致及 B/C 样包重算是工程实证，不是准确率。

## 样包 A：正式合成链与完整候选

C 归档 synthetic-formal-sample-v2-02 来自 formal-three-line-07，不是旧06重标。scored ZIP 87,474 B，SHA 8d17c009baf833f276ee456864bea0e6971fe43461d76d97b5d259441d5e9dac；base ZIP 82,198 B，SHA d8235ed41c2c3522f3f6bb4c087be70dc7ed3dddec5b86c120a572a48c20f24e。set hash 7e657cd1837300c08ffe28781f7d5ccc4f0501610f0cdca81e09da02f66562c9，assessment hash 1663a26790bf5ff979f07d315531f3f8bfad021c3a585aed0fa01aa9d3c1d73a；正式 verify 为10 hashes/ref true/assessment reproduced1，E新clean独立复验另留回执。

来源显式 SYNTHETIC；28次 Fake HTTP = analysis9 + translation9 + Judge10，真实模型/SMTP0。55 attempt DTO、27 outputs、12 forecasts、102 inputs、28 evidence、2 identities、7 truth revisions、set/assessment各1不是HTTP计数；同帖正文artifact复用1。Normal history2单列。Full/Banked各N1：首/末×24/48h，official栏各definite_hit1；Full inference栏undetermined1（顺序/目标范围冲突副标签），Banked inference栏no_prediction1。不能称模型或现实准确率通过；系列落空评价为NOT_FROZEN。

选取完整七天但 fixture 活动稀疏，仅 246 activity roots、5 个 UTC 日有活动；不是七日每日活跃的规模实证。C final05 有界压力 fixture 测得整库 1,536,000 B、相对同 schema 空库净增 1,220,608 B；账本两表及全部索引（含 SQLite autoindex）合计 1,179,648 B、净增 1,110,016 B。旧 1,130,496/1,077,248 B 为不含 autoindex 的历史口径，不作为本轮最终账本净增。141 raw artifact rows 与 243 ledger rows 不同于 110 DTO 投影/101 distinct/9 duplicate（7,124 重复 UTF8 B）。是测量，不按 HTTP 频率或年度增长外推。

## 样包 B、七天覆盖与体量

RO snapshot production-snapshot.sqlite：freeze2026-10-08T18:05:29.689073Z，SHA319ed41a1e16a0567d775c1ada3801d2614dfbd3f8d848dee0a36ceb99bf5a67；Schema7/20tables/integrityOK/FK0。scored acceptance 记录 source SHA 前后相同、DML/DDL attempts0。

真实 B：real-seven-day-scored-v2-01，完整窗口 [2026-10-01T18:05:29.689073Z,2026-10-08T18:05:29.689073Z)，同一 snapshot/freeze，max-records20,000 下 2parts/362activity roots，union assessment1/set1，ref/valid true、重算1。覆盖的是该 DB 的活动，不保证外部世界完整收集。

| scored B 文件 | bytes | SHA256 |
| --- | --- | --- |
| real-review-7d-v2-scored-part-0001.zip | 4,516,184 | caeae5375d0b3569e0fcc971cf6302bfc8d0a5afabad48632419e03f82d50aff |
| real-review-7d-v2-scored-part-0002.zip | 789,045 | 2e8fb7bd89bc5fa4d0b50edc778e01cb940fd5528f19420830765a948c108bda |
| real-review-7d-v2-scored.coverage.json | 见文件回执 | 2dc1e4969e436d7580b03b040e4356a2a1c8e3286938c4728b32e7a59620df73 |

两个ZIP合计5,305,229 B，生成/附入进程回执124.1606034s；E candidate 独立coverage验证113.3170908s。这些是含防护/本机环境的一次测量，不当长期性能保证。原 base-v2 ZIP大小4,512,217/785,275 B、过程45.9274936s是另一轮中间资产，不挪作 scored B。

acceptance 的 artifact measurement：18,618 artifact DTO投影、648 distinct version projections、17,970重复投影；UTF-8投影20,898,025 B、重复14,236,668 B。口径是最终 DTO等内容/版本，排除包身份/依赖装饰，不是原始 DB 新增行/增量存储或年度增长。core collection union另为23,039 public evidence、361 inputs/outputs、1 forecast、2 truths、0 attempts/identities，不与 artifact投影或362root互换。

旧约 2.86 GB/年仅为小型 synthetic fixture 线性估算，本轮不承诺年度增长。样本 A 与真实 B 均已由最终 clean 独立复验：A receipt 在 `runtime/review/prediction-three-lines-v1-20261009/e-clean-release-01/sample-a-verify/` 与 `sample-a-verify-assessment/`，B receipt 在 `runtime/review/prediction-three-lines-v1-20261009/e-clean-release-01/sample-b-coverage-verify/`。最终 acceptance 汇总见 `runtime/review/prediction-three-lines-v1-20261009/e-clean-release-01/acceptance-summary.json`；hash/ref 不等于现实准确率或外部资料完整性。

## 固定集评分：来源和分母边界

真实 scored B 集合仅依据持久化事件/truth identity，关联保持 unresolved，不造现代预测；Schema7 来源为 LEGACY_UNDECLARED。Full N=1 / Banked N=1；每个目标的首次/末次 × official_time_extraction/model_inference ×24/48h 面板均 no_prediction1，其他主分类0，分类和各等于N。这不是日期命中率成绩，不与synthetic/real/replay混总分；Normal单列。

缺 Banked预测/history/精确output availability不回填，hash/ref/重算不改变来源真实性。B synthetic与C完整功能链用于公式、绑定与工程验证，不是线上准确率。可信真值、事前性、关联或顺序不足的状态/副标签沿规范保留；N=0不可计算，辅助率不替代固定N。首次/末次和方法不挑最佳，宽区间覆盖不替代24/48h误差。公式未修改。

## 调用与运行隔离

| 操作 | 本轮实证 |
| --- | --- |
| 主动真实模型HTTP / Laya | 0 / 0，旧实验预算未用。 |
| 微信/邮件真实发送 | 0 / 0。 |
| 生产DB写入/迁移、服务启停 | 0；空库与读取候选库均在精确本轮_tmp。 |
| 历史 candidate Backend MockTransport HTTP | 75 次；仅属旧 candidate 证据。 |
| 最终 Backend MockTransport HTTP | 90 次，含模型和通知测试的模拟 HTTP；不是实际模型调用数，也不按 target 拆分。外部 socket/realHTTP/SMTP attempts 为 0。 |
| 直接 Fake JsonModel | profiled当前线程入口28，是局部计数，非完整跨线程Fake总数；不与75相加冒充完整调用数。 |
| empty smoke / coverage / v1 verify模型 | 0；GET/preview/verify/score不触发真实模型。 |

合成样本 A 的 28 次 Fake HTTP 由 C receipt 按操作计数；不得与最终 Backend MockTransport 90 次相加当作总请求，也不按 attempt DTO、outputs 或目标数倒推。自然生产后台活动不是本任务主动调用，也不据此宣称生产持续零调用。依赖下载不是模型请求。

## 最终离线收口与 Git 停点

A/C/D再次ready及主逻辑审查后，用新目录重冻结所有最新正式文件和tracked差异；三方hash/显式白名单、fresh dependencies身份、防护、完整Backend、受影响整套、smoke/两个样包/UI、Git diff-check/secret/bigfile/最终source comparison按实际回执收口。候选目录和旧结果不覆盖；不通过造.git、跳过/排除正式测试或改业务公式达标。

最终冻结 code/test manifest、完整 Backend、Web/Collector、smoke、样包、隔离 UI 和源码比较均已完成并有 runtime 回执。临时 helper 与运行证据留在事项目录；测试进程已退出。事项 `_tmp` 清理曾被环境策略拒绝，原路径保留，不绕过策略删除。

Git收口已完成：按显式互不重叠shiplist提交核心、评分、API-Web、导出、六文档五组；feature分支 `codex/prediction-three-lines-v1-20261009` 已普通push，草稿依赖PR [#11](https://github.com/Oblivionis-ling/codex-reset-radar/pull/11) 的base为 `codex/prediction-ledger-v1-20261007`，依赖仍开放的PR #10。代码与六文档提交头 `1893db2d05e1ac72682f45d870c6bcb547c1fae9` 的GitHub Actions run `37841210618` 中 backend、web、collector-extension jobs 均为 SUCCESS。后续仅文档元数据提交；最终提交头与其三项CI结论见 `runtime/review/prediction-three-lines-v1-20261009/git-closeout-01/receipt.json`。未改main、未打tag、未部署或触碰生产；未强推、未重跑本地测试、未调用模型。

## 四场景受控模型申请（预算已冻结，尚未授权）

申请已冻结于 `runtime/review/prediction-three-lines-v1-20261009/task12-controlled-candidates-02/index.json`，application SHA256 `64652941c3540edc24b77ed8ac8ab0763327f24f4a0c907d62dd524c7a86db7e`，selected model `deepseek-v4-flash`。四场景 HTTP 上限为 13 次（3+3+5+2）：2 个 acquired 真实文本与 2 个 synthetic 控制；已核实 1 个 exact analysis cache。analysis/translation 已冻结，最终 Judge hash 必须在真实 analysis 后再冻结；自动重试 0。申请状态 `NOT_AUTHORIZED`，没有发送请求。

| 场景 | HTTP 上限 | 已冻结组成 |
| --- | ---: | --- |
| 明确时区/日期的 Full 未来计划 | 3 | analysis 1、translation 1、共享双目标 Judge 1。 |
| 独立 Banked 计划、Full 无信号 | 3 | analysis 1、translation 1、共享双目标 Judge 1。 |
| 延期或已完成且另有下一轮 | 5 | analysis 2、translation 2、共享双目标 Judge 1。 |
| 普通内容/无时间依据 | 2 | exact analysis cache 1 项，analysis HTTP 0；translation 1、共享双目标 Judge 1。 |

申请已冻结并核实 exact analysis cache 1项；四场景最高 HTTP 请求数13（3+3+5+2，失败计入），完整终点预留后串行，不新增全年回放/抽结果重试。申请仍为 `NOT_AUTHORIZED`，没有发送请求；真实缺口保持、虚构控制单列。仅获批实测后更新模型语义，小集合仍不保证准确率或授权生产启用。
