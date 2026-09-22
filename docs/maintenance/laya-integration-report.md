# Laya 接入记录

状态：**INTEGRATED_BUT_QUALITY_NOT_ACCEPTED**。安装和隔离 DB/API 实链成立，质量门槛失败；
生产保持 `deepseek_only`，不创建生产版本标签。实际浏览器视觉验收尚未完成，不能称全部验收通过。

## 接入前恢复点

已核验 GitHub 上的分支 `archive/pre-laya-20260922T072045Z` 和 annotated tag
`pre-laya-20260922T072045Z`，目标均为 `73d7a7e1ecd9f5e70d4e5f6d80fa38a79c85931b`。
83 个新可达 blob 的秘密、禁止资产和大文件检查未发现问题。
PR [#6](https://github.com/Oblivionis-ling/codex-reset-radar/pull/6) 的 Backend、Web、Collector CI
（run `35699156352`）通过后正常合并。Laya 开发位于独立 `feature/laya-decision` 分支。
本地恢复回执：`runtime/laya-integration-20260922/pre-laya.json`。

## 预先固定的评估边界

- 最多 48 次真实 DeepSeek HTTP 尝试（包括重试）；最多两个 checkpoint、两轮有原因的问题修订。
- 14 个已裁定窗口是开发回归，不是独立预测准确率测试。人工四字段不修改。
- 效果不低于本轮同输入的 DeepSeek-only；不接受新增重要漏报或用大量回退掩盖 Laya 原始差异。
- 安全保护、超时回收、原模式恢复、DB/API/UI 实链未通过，不启用生产 hybrid。
- CPU 冷启动预算 90 秒、暖推理 15 秒；2 个线程、一次一个请求、一个常驻模型。
- 所有模型结果、请求、权重和数据库仅放 Git 忽略的本地目录。真实微信/邮件发送均为 0。

## 实际硬件与依赖

本机为 i7-12700、20 逻辑处理器、约 15.7 GiB RAM、Intel 集显；未发现可用 NVIDIA CUDA。
G 盘不存在，因此使用 `runtime/laya/`，不修改全局缓存或系统驱动。
Backend 原虚拟环境不安装重型依赖；独立环境是 `apps/laya-worker/.venv/`。

已安装 Python 3.12 环境、Laya 0.3.5、torch 2.6.0+cpu、transformers 4.51.3、
huggingface_hub 0.36.0、safetensors 0.5.3、numpy 2.2.6、psutil 7.0.0、hf-xet 1.6.0。
SDK 与 PyPI 本次均确认 0.3.5；不沿用任务书中的旧版本差异。

安装命令（PowerShell，项目根目录）：

```powershell
apps/backend/.venv/Scripts/python.exe -m venv apps/laya-worker/.venv
$env:PIP_CACHE_DIR = "$PWD/runtime/laya/cache/pip"
apps/laya-worker/.venv/Scripts/python.exe -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
apps/laya-worker/.venv/Scripts/python.exe -m pip install -r apps/laya-worker/requirements.txt -c apps/laya-worker/constraints-windows-cpu.txt
apps/laya-worker/.venv/Scripts/python.exe apps/laya-worker/install_model.py --revision 1c5edc17a7acd8701df6fc341c0d179f1c62c982 --root runtime/laya --http-download
```

模型固定为 `convaiinnovations/laya` revision `1c5edc17a7acd8701df6fc341c0d179f1c62c982`。
官方权重大小 842,609,210 bytes，LFS SHA256
`891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c`。
普通下载和 Xet 路径未取得有效进展；官方 `download=true` CDN 成功，下载后大小与 SHA256 核验通过。
没有第三方镜像、关闭 TLS 或更改全局代理。最终本地路径为 `runtime/laya/models/laya-1c5edc17a7ac/`。

第二个且最后一个候选为 `convaiinnovations/laya-typed-decisions`，revision
`f9ab0b228f0fc0f14d873dbc99038f135c2da1b2`，本地路径
`runtime/laya/models/laya-typed-decisions-f9ab0b228f0f/`，权重 SHA256
`4fa56de72383a9d3efa9cfa78955733c81b9fc8067a587ca4beb82c78107a24e`。
安装使用同一命令，替换 `--checkpoint`、`--revision`，不改 SDK，不训练。
两个模型均实际运行于 CPU / float32；工件为 safetensors，启动进行本地完整性校验。

## 正式实现与已发现缺口

- `hybrid_decision.py` 复用原上下文和 Provider，生成中性证据，再请求本地四色与时间候选 choice；不写事件或周期。
- `laya_worker.py` 管理私有 stdio 子进程；异步读写、单请求锁、超时 kill + wait，无公开监听端口。
- `apps/laya-worker/worker.py` 只离线读取完整本地工件。按实际 tokenizer 重现 SDK 预算，任何截断都拒绝。
- 下载层固定 revision；保留 HF 原快照，独立 tokenizer 兼容配置记录源/有效 SHA256。启动验证工件。
- 旧模式仍使用原 Judge；hybrid 的失败回退记录引擎与原因，不计为 Laya 成功。
- DB 继续通过原 `raw_json → raw` 边界；API 区分引擎模式，过期、内容、父帖、周期保护不取消。
- 发现没有 `post_id` 的导入案例可按关联 Tweet ID 返回待测内容；新增稳定 ID 与同事件证据排除，不改人工答案。
- API 新元信息在损坏 raw 上的空值异常已由既有回归捕获并修复。
- 实际复现的强预警与空支持论据矛盾，改为 `UNSUPPORTED_STRONG_DECISION` 拒绝并回退；不改原始颜色。
- 父帖引用只允许真实输入节点，公开证据关联其受版本管理的回复；审计包保留父帖引用，不能冒充 Tibo 原文。
- 回显 `as_of`/`data_health` 仅在与输入完全一致时接受，冲突拒绝；其余未知字段仍拒绝。
- RemoteProtocolError 计入统一失败日志与请求预算。未增加 Adapter 重试层。

Evidence Prompt：`crr-evidence-1`；Question Schema：`crr-laya-choice-1`；
最终校验版本：`crr-decision-validation-2`。未调优问题答案，未引入 GPT 四色到证据包。
旧 Judge Prompt 仍为 `v2-reset-judge-8-context-health`；分析、翻译 Prompt 未改动。
没有跨请求的决策缓存；重评沿用原调度。第二 checkpoint 复用冻结真实证据，回退只能复用同一
as_of、上下文哈希、模型和旧 Judge Prompt 的合法基线结果，不把复用计为新模型调用。

## 14 窗口真实对照

原人工决定文件哈希已按已有清单校验，未修改。每个窗口单独隔离数据库，原旧判断移出测试输入；
两路输入上下文哈希相同。第一轮 hybrid 使用校验修正前版本，失败原件保留；第二候选使用最终校验。
上游复用历史 v5 全量分析与 v8 定向覆盖，**不是 v9 全库重跑**。
历史案例关联 Tweet ID/同事件排除是本轮输入变化，旧模式同步采用；原 Prompt 已含历史人工校准，
这 14 项只能称开发回归一致性，不能称独立预测准确率。

| 运行 | 完成/总数 | 四字段一致/14 | 单字段一致/56 | 最终纯 Laya | 回退 | 原始 Laya 完全一致/有输出 |
| --- | --- | --- | --- | --- | --- | --- |
| DeepSeek-only | 13/14 | 10/14 | 43/56 | — | — | — |
| base（修正前） | 13/14 | 6/14 | 32/56 | 5 | 8 | 0/6 |
| typed（最终校验） | 13/14 | 7/14 | 36/56 | 3 | 10 | 0/8 |

typed 的 7 个完全一致全部来自旧模式缓存回退，不是 Laya 答对。base 原始结果包含 3 个错误红灯字段；
typed 原始结果包含 7 个错误红灯字段、4 个重要等级低估字段（J12 的四个 RED 被选为 ORANGE）。
这些是各自实际产生原始结果子集的计数；拒绝、缺资料和失败窗口仍留在 14 项分母，不计算选择性准确率。

下表等级顺序为主/24/48/72h。G=GREEN，Y=YELLOW，O=ORANGE，R=RED。
第二候选最终列的“回退”均复用同输入旧模式结果；没有额外付费调用。

| 窗口 | as_of（2026，UTC） | 人工 | 旧模式 | typed 最终 | 来源 |
| --- | --- | --- | --- | --- | --- |
| J1 | 08-27 12:00 | O/O/R/R | O/O/R/R | O/O/R/R | 回退 |
| J2 | 08-27 17:00 | G/G/G/Y | G/G/Y/Y | G/G/Y/Y | 回退 |
| J3 | 08-29 12:00 | O/O/R/R | O/O/R/R | O/O/R/R | 回退 |
| J4 | 08-29 21:10 | G/G/Y/Y | Y/Y/O/O | Y/Y/O/O | 回退 |
| J5 | 08-30 00:00 | Y/Y/O/O | O/O/R/R | O/O/R/R | 回退 |
| J6 | 08-31 03:00 | G/G/G/Y | G/G/G/Y | G/G/G/Y | 回退 |
| J7 | 09-03 23:30 | G/G/G/Y | G/G/G/Y | G/G/G/Y | 回退 |
| J8 | 09-04 23:00 | G/G/G/Y | G/G/G/Y | G/G/G/Y | 回退 |
| J9 | 09-05 02:00 | G/G/G/Y | G/G/G/Y | G/G/G/Y | 回退 |
| J10 | 09-08 05:00 | G/G/G/Y | G/G/G/Y | Y/G/G/G | Laya |
| J11 | 09-09 19:00 | G/G/G/Y | G/G/G/Y | G/G/G/G | Laya |
| J12 | 09-12 04:00 | R/R/R/R | R/R/R/R | O/O/O/O | Laya |
| J13 | 09-12 09:00 | G/G/G/Y | G/G/G/Y | G/G/G/Y | 回退 |
| J14 | 09-14 08:00 | G/G/G/Y | 失败 | 失败，无合法回退 | 保留失败 |

J14 基线首次失败只留有 ValueError 和调用记录，未在保存前归档供应商答案；不能补造具体原因。
后续全部证据请求/响应已保存在本地审计文件。其他失败包括空/非法引用、字段契约、供应商协议错误、
JSON 解析、窗口逆序和无支持的强决策，未重复调用直到匹配参考。

独立留出限制：现有 20 个案例不是另 20 个人工四色窗口，检查到早期事件案例仍为
`UNREVIEWED`、`EVENT_RECOGNITION`、已有产品参考暴露。不能伪造独立四色标签。
本轮新回复组不参与模型选择/问题修改的评分，但没有人工四色参考，因此只验证上下文和工程链路。

## 真实回复到 API

生产一致性只读快照：`runtime/laya-integration-20260922/production-readonly-snapshot.db`，
`integrity_check=ok`、外键检查为空。冻结时 405 帖、14 正式事件，原生产库不改写。
目标回复 `2101352781219258527`，直接父帖 `2101093319501664368`，状态 READY；当前上下文确实包含它。

同一已分析版本经持久任务再次完成，分析/翻译缓存命中，新增上游模型调用 0。
首次当前链调用证据和旧 Judge 各一次，旧回退引用缺输入版本，API 正确拒绝，不能算成功当前判断。
修正契约后复用这份真实 DeepSeek 证据，由 typed 在本机推理，**隔离库**保存 Judge #267，
校验 `VALID`，正式 Radar 路由返回 `decision_engine=laya`、`display_mode=current`、O/O/O/O，
forecast 为 UNKNOWN，未制造确定的周二日程。证据包哈希：
`7755fd49d51eefc9aaa562ab5b89a7340bd15fedec1fe3d6a7ab5c2fabfd7932`。
这不是对其颜色作人工批准，也不是生产 Judge #267。

事件与周期未因 Laya 推理新增或改变。采集日志显示测试期间持续真实 `POST_BATCH_INGESTED`；
没有为验收向生产伪造心跳或帖子。API 调用通过原应用路由，不从参考文件构造响应。
前端已增加引擎/回退数据绑定，未改视觉；浏览器工具因不能可靠确认 URL 安全停止，
**实际页面显示仍待核验**，未以工具错误宣称项目停机。

## 资源、费用与稳定性

全部主动真实 DeepSeek HTTP 尝试 **39 次**：旧模式 14、第一轮 hybrid 23、当前链 2。
第二 checkpoint 和稳定性测试复用冻结证据，没有新增 DeepSeek 调用。日常自然调度另计，未主动触发生产重判。
已成功响应报告的 usage 合计 prompt 546,101、completion 165,869、total 711,970 tokens；
失败调用计费未知，未核实当前供应商单价，故不编造金额。

| 指标（秒） | 旧模式 | base | typed |
| --- | --- | --- | --- |
| 全路径 p50 / p95 | 13.98 / 19.55 | 48.16 / 93.98 | 不可直接比较：复用证据及回退缓存 |
| 本地推理 p50 / p95 | — | 6.55 / 8.56 | 7.40 / 12.56 |
| 首次记录的冷启动 | — | 21.47 | 7.16（OS 文件缓存已暖） |
| 观测进程 RSS 最大值 | — | 约 1.95 GiB | 约 1.96 GiB |

typed 当前回复场景推理 10.72 秒，状态 585 tokens，最长完整输入 653 tokens，未截断。
base 上限 512、typed 1024，均保持发布工件原配置；没有简单调大 max_len。
CPU 无显存数据，不引用 T4 宣传时延。更多本地模型没有体现为更低的实际全链时延或调用成本。

只做了一次选项倒序、一次等义改写（同一当前材料，结果相同）；不以此声称普遍稳定。
真实 tokenizer 的超长故障注入得到 `INPUT_TOO_LONG`，离线重启成功，STALE 元信息不被改为 HEALTHY。
失败、取消、超时回收及缺权重用离线测试覆盖，非实测 CUDA OOM。

## 回归与发布记录

初次干净检出：Backend 104、Web 7、Collector 18 项通过，Web/Collector 类型检查和构建通过。
随后增加父帖、支持论据和协议故障测试，最终测试与功能分支 CI 结果在本节收尾记录。
正式源码不依赖 `_tmp` 工具；旧模式不需要 Laya 环境和权重。模型、环境、完整语料、日志和数据库不提交。
功能分支发布不等于质量验收或主线合并；现有 main/Alpha 4 维持已接受模式。

本地统一回执：`runtime/laya-integration-20260922/acceptance.json`。
主要差异与原件：同目录下 `comparison-baseline.json`、`comparison-hybrid.json`、`comparison-typed.json`、
`current-chain-acceptance.json`、`current-chain-typed-acceptance.json`、`stability.json`。
完整模型请求与真实文本仅在该忽略目录下 `private-attempt-*.json` 中，不能上传。

剩余限制：质量未达标；J14 缺合法旧模式回退；没有独立人工四色留出集；浏览器视觉验收待核验。
不继续扩大语料、不新增模型或反复调参、不替用户接受这些差异。

## 禁用与恢复

`CRR_DECISION_MODE=deepseek_only` 保持旧模式，不需要 Laya 环境和权重。
切换只按现有安全启停方式操作本项目服务；不得因特性测试关闭日常 Edge 或其他进程。
本轮尚未切换生产模式，也未修改生产数据库。

## 官方核查来源

- [SDK](https://github.com/NandhaKishorM/laya)，检查源码 revision `573e5b62696ba441230cd6be71d593331b5d23af`。
- [PyPI](https://pypi.org/project/laya/0.3.5/)
- [模型快照](https://huggingface.co/convaiinnovations/laya/tree/1c5edc17a7acd8701df6fc341c0d179f1c62c982)

SDK 为 Apache-2.0；工件保持官方许可记录，不上传权重。官方 T4 演示时延不作为本机指标。
