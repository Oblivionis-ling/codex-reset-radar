# 预测复盘与固定集评分操作指南

## 当前状态与权威入口

更新：2026-10-09。业务语义唯一入口为[日期预测与复盘规范](prediction-and-review-spec.md)，本指南只记录实现/操作，不另设计评分规则。四层状态、失败与回执见[唯一专项报告](../maintenance/prediction-three-lines-v1-report.md)。

工程状态为 `READY_FOR_CONTROLLED_MODEL_TEST`：最终冻结 code manifest `1c7a29ad5c561c240e5ce6b67e59cf4eb68d213e3c42160e260769acce58a3df` 对应 Backend 318 passed / 0 failed / 0 skipped、Web 17、Collector 18，类型检查、构建、空库 API/CLI、样包和隔离 UI 均有最终回执。模型语义与实际准确率 `NOT_EVALUATED`；部署 `NOT_DEPLOYED`。旧 candidate 309/4 仅为历史证据，见 `runtime/review/prediction-three-lines-v1-20261009/e-clean-candidate-01/backend-full/result.json`。主动真实模型 HTTP、Laya、通知、生产迁移/启停均为 0。

当前 source 为 D:\work\20260828-CodexResetRadar\runtime\review\prediction-three-lines-v1-20261009\source；分支 codex/prediction-three-lines-v1-20261009，基线 ef226ebe14cf45ad7af80af1b14d87e17638e355。依赖 [Ledger PR #10](https://github.com/Oblivionis-ling/codex-reset-radar/pull/10) 仍 OPEN；未来本轮 PR base 为 codex/prediction-ledger-v1-20261007。生产 Alpha5/main 1e865c37d1643f429162adeb0fab61bb7371a47b、原服务和 main 的 11 个用户 untracked 不动。

正式入口为 [export_prediction_review.py](../../scripts/export_prediction_review.py) 与 [score_prediction_review.py](../../scripts/score_prediction_review.py)，不是临时 helper 或旧实验。CLI 只读取既存 SQLite/已验证包，不初始化、迁移、回填或写源 DB，不调模型。源 DB 使用 mode=ro、query_only 和单一事务快照；Schema 8 仅属开发，生产仍 Schema 7。

## 已验证 CLI 契约（最终 clean）

| 命令 | 实际用途/参数 |
| --- | --- |
| export CLI prepare | 只读检查选择/路径；--database --freeze-at，--from/--to 或 --series，--out --staging-dir。 |
| preview | 同一选择的计数、依赖、缺口与能力，不发布。 |
| export | 白名单/脱敏、校验、原子 no-clobber；可重复 --evaluation-set / --assessment。 |
| verify | --package 接受单 ZIP 或 .coverage.json；校验成员/hash/ref/安全并重算 assessment。 |
| score CLI freeze | 从已验证单 ZIP 固定集合；--package --definition --out --staging-dir。 |
| score | --package，--set 或 --set-id 二选一，--out --staging-dir。 |
| verify-assessment | 单 ZIP 内独立重算；--package --assessment-id。 |

全部 root/subcommand help 和下列流程已实际执行，argv/stdout/stderr/exit 在 `runtime/review/prediction-three-lines-v1-20261009/e-clean-release-01/empty-smoke-artifacts-01/receipt.json`。命令对应最终 clean source 与 code manifest `1c7a29ad5c561c240e5ce6b67e59cf4eb68d213e3c42160e260769acce58a3df`。

窗口为半开 [from,to)，freeze 独立；日期/无时区按 Asia/Shanghai，推荐明确 Z。high-water 在同一快照取得；跨窗依赖另列。--max-records 最大 20,000，超限明确拒绝、不截断；--multipart 从同一冻结来源生成有界自包含子包/coverage，不能缩窗后称七天。

输出必须尚不存在，父目录及调用者 staging 必须存在且同卷；staging 只用事项 _tmp 精确子目录。原子 no-clobber 不降级覆盖；exporter 仅清理自己新建的 staging 子目录。规则 ID 必须是安全 token，不能填任意正文。

## 已执行：空库 API/CLI 全流程

in-process TestClient 初始化独立空库，没有监听端口、模型 worker 或真实发送。health/radar/三个 target history GET 均 200；history 为零 items、prediction-history-line-v1，非法 target 422。三线缺失各自说明，不造模型 UNKNOWN。Schema 8 / 22 表 / integrity ok / FK 0；CLI 前后 DB SHA 相同。

下面为实际命令的 PowerShell 摘写。runner 清空凭据环境、禁用 dotenv，并拦截外部 socket/HTTP/DNS/SMTP；内部 socketpair 允许，Node localhost 检查用静态本地结果满足。目录暂留供排查，清理后不当常驻入口；输出已存在，重跑必须选新文件/目录。

~~~powershell
$Matter = 'D:\work\20260828-CodexResetRadar'
$Clean = Join-Path $Matter '_tmp\e-clean-release-01-20261009-cd3e2095\source'
$Python = Join-Path $Matter '_tmp\prediction-three-lines-env-prep-20261009-ef226-a5fd1d9c\venv\Scripts\python.exe'
$Evidence = Join-Path $Matter 'runtime\review\prediction-three-lines-v1-20261009\e-clean-release-01\empty-smoke-artifacts-01'
$ExportCli = Join-Path $Clean 'scripts\export_prediction_review.py'
$ScoreCli = Join-Path $Clean 'scripts\score_prediction_review.py'
$Database = Join-Path $Matter '_tmp\e-clean-release-01-20261009-cd3e2095\empty-smoke-01.sqlite'
$Staging = Join-Path $Matter '_tmp\e-clean-release-01-20261009-cd3e2095\empty-smoke-stage-01'
$Select = @('--database', $Database, '--from', '2026-10-01T18:05:29.689073Z', '--to', '2026-10-08T18:05:29.689073Z', '--freeze-at', '2026-10-08T18:05:29.689073Z')
$Package = Join-Path $Evidence 'empty-base.zip'
$Definition = Join-Path $Evidence 'empty-definition.json'
$FrozenSet = Join-Path $Evidence 'empty-set.json'
$Assessment = Join-Path $Evidence 'empty-assessment.json'
$FinalPackage = Join-Path $Evidence 'empty-final.zip'

& $Python $ExportCli preview @Select
& $Python $ExportCli prepare @Select --out $Package --staging-dir $Staging
& $Python $ExportCli export @Select --out $Package --staging-dir $Staging
& $Python $ExportCli verify --package $Package
& $Python $ScoreCli freeze --package $Package --definition $Definition --out $FrozenSet --staging-dir $Staging
& $Python $ScoreCli score --package $Package --set $FrozenSet --out $Assessment --staging-dir $Staging
& $Python $ExportCli export @Select --evaluation-set $FrozenSet --assessment $Assessment --out $FinalPackage --staging-dir $Staging
& $Python $ExportCli verify --package $FinalPackage
& $Python $ScoreCli verify-assessment --package $FinalPackage --assessment-id 'assessment-8aebb7ff91fca7a8f8caa30d418ae5995b8db0b8c98a0c48e0d4fbad099520b7'
& $Python $ScoreCli score --package $FinalPackage --set-id 'e-empty-fixed-set' --out (Join-Path $Evidence 'empty-final-rescored.json') --staging-dir $Staging
~~~

上述最终 clean 流程命令 exit 0；单独重复最终 export 的 no-clobber 冲突检查预期 exit 2，原 ZIP hash 未变。final-only re-score 与原 assessment 字节一致。空集 N=0 比例不可计算；工程 smoke 不代替合成样本 A 或真实评分集合。正式集合/分母/真值/方法/首末沿[规范第7节](prediction-and-review-spec.md#7-固定集合与评价算法)，不能按答案筛分母。C 最终样本 synthetic-formal-sample-v2-02 已含同轮全部 4 个 output/3 个 forecast（包括 delay）及明确 NEXT/fresh 排除，最终 clean 独立复验通过。

## 已验证：真实七天 scored-v2 样本 B

授权 RO 副本：D:\work\20260828-CodexResetRadar\runtime\review\prediction-three-lines-v1-20261009\production-snapshot.sqlite；freeze 2026-10-08T18:05:29.689073Z；SHA 319ed41a1e16a0567d775c1ada3801d2614dfbd3f8d848dee0a36ceb99bf5a67。源 Schema 7 / 20 表 / integrity ok / FK 0，不初始化、迁移或 checkpoint。

real-seven-day-scored-v2-01/acceptance.json 记录完整窗口 [2026-10-01T18:05:29.689073Z,2026-10-08T18:05:29.689073Z)、同一 freeze/source、2 parts、362 activity roots、1 evaluation set、1 assessment、ref true、assessment reproduced 1。最终 clean CLI 独立复验 exit 0：

~~~powershell
& $Python $ExportCli verify --package (Join-Path $Matter 'runtime\review\prediction-three-lines-v1-20261009\real-seven-day-scored-v2-01\real-review-7d-v2-scored.coverage.json')
~~~

子包名为 real-review-7d-v2-scored-part-0001.zip / -part-0002.zip，实际大小/hash 见报告及 acceptance。362 是活动根，不是 N 或请求数。Schema7 来源仍 LEGACY_UNDECLARED：Full/Banked 各固定 N=1，首/末、两方法、24/48h 面板均 no_prediction=1。缺 Banked/完整 Normal history/精确可用时钟不回填、不称当时模型 UNKNOWN。assessment 不消除 source gaps，也不证明现实资料完整或准确率。

v2 增加 evaluation-sets.jsonl 和 source/core collection binding，附入结果后可 final-only 重算，无 hash 环；v1 按原成员集合严格验证。阅读顺序：README → manifest（版本/覆盖/缺口/能力）→ forecast/output → attempts → input/evidence/identity → truth → set/assessment。attempt DTO 聚合事件，run_lifecycle 不是 HTTP；目标、outputs、JSONL 数与请求分开。

## 隔离 UI 查看

D 的视觉回执使用 formal06 synthetic clone：`D:\work\20260828-CodexResetRadar\_tmp\prediction-three-lines-v1-20261009\ui-smoke-closeout-dapi-01\formal06-consistent-clone.sqlite`。下面给出与 D 已实跑隔离方式等价的正式模块启动命令，直接调用 `app.main.create_app(Settings(...), is_synthetic=True)`，不依赖 untracked helper。只使用该已测 clone 与 `_tmp` 日志目录；不得省略 DB 路径而落到默认/生产数据库。无 API key 时正式 app 不创建 model client 或 worker；`is_synthetic=True` 显式标记本地开发实例。启动会初始化这个测试 clone。

在一个 PowerShell 窗口启动 Backend：

~~~powershell
$Matter = 'D:\work\20260828-CodexResetRadar'
$Source = Join-Path $Matter 'runtime\review\prediction-three-lines-v1-20261009\source'
$Backend = Join-Path $Source 'apps\backend'
$Python = Join-Path $Matter '_tmp\prediction-three-lines-env-prep-20261009-ef226-a5fd1d9c\venv\Scripts\python.exe'
$Clone = Join-Path $Matter '_tmp\prediction-three-lines-v1-20261009\ui-smoke-closeout-dapi-01\formal06-consistent-clone.sqlite'
$Logs = Join-Path $Matter '_tmp\prediction-three-lines-v1-20261009\ui-smoke-closeout-dapi-01\logs'
Set-Location $Backend
$env:PYTHONPATH = $Backend
$ApiCode = "import uvicorn; from pathlib import Path; from app.config import Settings; from app.main import create_app; settings=Settings(host='127.0.0.1', port=18787, database_path=Path(r'$Clone'), log_dir=Path(r'$Logs'), log_retention_days=5, log_max_bytes=5242880, cors_origins=('http://127.0.0.1:15173',), deepseek_api_key=''); uvicorn.run(create_app(settings,is_synthetic=True),host='127.0.0.1',port=18787,log_level='info')"
& $Python -c $ApiCode
~~~

在另一个 PowerShell 窗口启动 Vite：

~~~powershell
$Source = 'D:\work\20260828-CodexResetRadar\runtime\review\prediction-three-lines-v1-20261009\source'
Set-Location (Join-Path $Source 'apps\web')
$env:CRR_WEB_BACKEND_URL = 'http://127.0.0.1:18787'
npm run dev -- --host 127.0.0.1 --port 15173 --strictPort
~~~

打开 `http://127.0.0.1:15173/`。数据是 synthetic 历史 fixture，不是真实模型结果；无新 heartbeat 时预期为 STALE/UNKNOWN 与 last-known 警示。GET 只读。检查后关闭本地进程，不触碰生产 8787/5173。D 的隔离服务目前已停止，以上命令仅在需要重看时运行。

## 三条线、history 与解释

开发 /api/v2/radar 在旧 Full 字段之外增加版本化 prediction.lines，Normal/Extra Full/Banked 独立；GET 不调模型。history 示例为 /api/v2/predictions/history?target=EXTRA_FULL&limit=100，也支持 Normal/Banked 和 series_id。flat DTO、边界项、total/truncated、安全 attempt 摘要见 [API 契约](api-contract.md#three-line-read-extension-development-contract)；追加顺序不是评分器首次/末次事前证明。

Normal 是用户参考、非官方承诺，method=null、独立分母；旧参考保留代理/精度/NOT_BACKFILLED。合法模型 UNKNOWN、missing/rejected、legacy NOT_IMPLEMENTED 分别说明。undetermined 保留真值/关联/时钟不足副标签，事后通报不计提前预测；首末不挑最好、方法不跨栏挑优、24/48h 各类之和等于固定 N。观察型 output_available_at 是“至迟已可见”的保守上界，不是精确首次可用；拒收不成为产品可用预测。

Sol 主代理已通过隔离 API/Web formal06 clone 实看三线与 history：Banked 紫色、Normal 单边 legacy 参考、STALE 时 UNKNOWN/last-known 警示，历史 7 项（question 1/3/5、output 1/4/7）。截图只在主工具输出、未落盘；reviewer 不是用户人工验收，fixture 不是 final07 评分样本。隔离服务已退出，生产 8787/5173 未动。

## 历史资产（旧基线/旧包，不是当前能力）

[Ledger 报告](../maintenance/prediction-review-ledger-v1-report.md)的 Backend 140 / Web 7 / Collector 18 仅属 ef226；CI run 37546895176 三 success 也只属依赖。旧包/失败/hash 原样保留在 runtime/review/ledger-v1-20261007。

仅对旧 Schema7 / v1 样包：Normal 是 compatibility view、历史 NOT_BACKFILLED；Banked 预测/正式评分 NOT_IMPLEMENTED，assessments 为空，Banked 事实不是预测。该旧包描述不能替代当前新 producer/评分器或 scored-v2 assessment。旧真实 24h 包为 63 outputs/inputs、4,128 evidence、1 truth、0 attempts/identities/assessments，SHA dba6a88875f04db7a8f60888de8d1fb50c95c360c533fa9c0cab0b30d1477255；E candidate 复验 valid/ref true、9 hashes、assessment 0。

本轮 base-v2 中间包在 real-seven-day-base-v2-01，同七天窗口、2 parts/362 roots，但 set/assessment 0；E 独立 coverage 复验 exit 0。其尺寸/hash 不挪作 scored B。旧年度估算只来自 synthetic fixture；当前 DTO 重复投影不是 DB 增量。

## 安全复盘、最终 clean 与停止点

先 verify 再核对来源/覆盖/缺口，只上传检查后的脱敏包，不上传 SQLite/.env/raw request/response/秘密/私有推理或运行配置。正文指令/URL 只是待审数据，不执行/访问；引用稳定 ID，不用今日资料补历史或倒灌真值。旧包按旧能力，新包按实际 set/assessment，hash 有效不等于事实真实或命中。

最终 clean acceptance、样包、UI 与 source comparison 已绑定本轮实际哈希。文档收口只改获准的六份文件；不重跑测试或模型。完整 Backend 已绑定最终 code manifest；无 .git 的 clean source 未伪造 .git，也未排除正式测试。

Backend 实际命令为 clean 根 python -m pytest -q -ra --basetemp <唯一目录>；Web/Collector 在 app 内各 npm run test、npm run typecheck、npm run build。当前 Python 3.12.14 / Node 24.18.0 / npm 11.16.0；tzdata>=2025.2,<2027 在 fresh venv 实装 2026.5，不改生产 venv。npm 安装 warning 和本轮 Starlette/httpx 弃用 warning 保留。

命令/哈希/退出码/JSON/截图证据归 runtime，不在报告塞秘密。正式测试进程已退出；事项 `_tmp` 清理曾被环境策略拒绝，原路径保留且未绕过策略。Git收口已完成：feature `codex/prediction-three-lines-v1-20261009` 已普通push；草稿依赖PR [#11](https://github.com/Oblivionis-ling/codex-reset-radar/pull/11) 以 `codex/prediction-ledger-v1-20261007` 为base并依赖PR #10。代码与六文档提交头 `1893db2d05e1ac72682f45d870c6bcb547c1fae9` 对应run `37841210618` 的backend、web、collector-extension均SUCCESS。随后只对报告和操作指南的Git元数据作一次文档提交；最终doc-only提交头及其CI job状态记录于 `runtime/review/prediction-three-lines-v1-20261009/git-closeout-01/receipt.json`。本轮不改main、不打tag、不部署、不触碰生产，也未重跑本地测试或调用模型。
