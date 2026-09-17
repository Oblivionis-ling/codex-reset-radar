# Codex Reset Radar V2 历史语料报告

> 本文是第一轮导入时点报告。最新数据库数字、2025 种子处置与 Schema v5 结论见
> [historical-corpus-round2-report.md](historical-corpus-round2-report.md)。

## 1. 结论

截至 2026-09-17，本轮已经完成一批真实、可追溯、与实时链路隔离的历史语料导入，并把经过人工整理的历史案例接入现有 DeepSeek Judge。

- 固定目标窗口：`2025-09-17T01:35:00Z` 至 `2026-09-17T01:35:00Z`。
- 实际取得外部资料：81 条来源证据，覆盖 2026-03-03 至 2026-09-14。
- 首次导入：新增 38 条 Tweet，补全/提高 25 条既有记录的原文或证据等级。
- 语料版本：`corpus-20260917-b3e38dcf3bf4@2026-09-17T01:35:00Z`。
- Judge 可用案例：8 个，其中 5 个 Full Reset 关联案例、1 个 Special Reset、2 个 `UNKNOWN` 对照案例。
- 实时污染：0 个历史导入任务进入 realtime queue，0 次逐条 Judge，0 次通知发送。

这不是完整的 Tibo 历史档案。当前成果应表述为“已取得并登记部分资料”，不能据此声称目标 12 个月已经全部覆盖。

## 2. 来源与实际导入

详细来源登记见 [source-register.md](source-register.md)。本轮实际导入两个公开来源；Gussuri 只用于发现与交叉核对，没有把其分类直接写成 V2 正式事实。

| 来源 | 取得方式 | 证据数 | 首次新增 | 首次补全 | 首次重复 | 首次冲突 | 资料性质 |
|---|---|---:|---:|---:|---:|---:|---|
| ModelYard | 公开 HTML 内嵌数据，1 页 | 35 | 1 | 24 | 0 | 10 | 来源标为 `DIRECT_VERIFIED` 的英文副本；该标记仍保留为来源声明 |
| AIPlanWatch | 公开历史页，低频读取 2 页 | 46 | 37 | 1 | 3 | 5 | 带 Tweet ID/原帖链接的第三方引文与分类声明 |
| 合计 |  | 81 | 38 | 25 | 3 | 15 | 不自动升级为正式 Reset |

同一稳定 batch prefix 的验收重跑结果为：ModelYard `25 duplicate + 10 conflict`，AIPlanWatch `41 duplicate + 5 conflict`，新增和补全均为 0。这证明帖子、来源证据和案例没有因重跑而重复。

本地完整快照位于被 Git 忽略的 `data/corpus/imports/historical-20260917T0135.json`。仓库只保留导入器、测试、数据策略和脱敏报告，不公开转载完整语料。

## 3. 导入后数据库盘点

| 项目 | 数量 |
|---|---:|
| 全部帖子 | 341 |
| realtime 帖子 | 303 |
| historical-only 帖子 | 38 |
| 来源证据 | 81 |
| 历史案例 | 8 |
| 正式 Reset 事件 | 5 |
| Radar judgements（验收时） | 83 |

全部 341 条帖子当前处理状态：

| 状态 | 数量 | 含义 |
|---|---:|---|
| `COMPLETED` | 38 | 已完成当前语义分析 |
| `PENDING` | 251 | 较早 realtime 存量，尚未批量调用模型 |
| `FAILED` | 7 | 保留失败状态，未伪装为已处理 |
| `HISTORICAL_UNANALYSED` | 45 | 38 条 historical-only，加上 7 条因可靠英文原文补全而需重新分析的既有 realtime 记录 |

语言盘点为英文 267、中文 71、未知 3。中文记录保留为实际采集到的浏览器译文或显示译文，没有反向生成英文“原文”。

## 4. 原文、完整度与冲突

证据级质量如下：

- `direct_verified`：35 条，均来自 ModelYard 的来源声明。
- `source_quoted`：46 条，均来自 AIPlanWatch。
- 可能截断：14 条证据；其余 AIPlanWatch 引文仍为“未独立确认完整”。
- 带完整回复上下文：0 条；全部明确标为 standalone/无上下文。
- 文本冲突证据：15 条，其中 ModelYard 10、AIPlanWatch 5。

API 的 `corpus.conflicts` 现在采用“冲突证据行”口径，值为 15。规范帖子层另有 20 条带冲突处置状态：12 条仍为 `text_mismatch_preserved`，8 条为 `resolved_prefer_direct_original`。两种口径不能相加：同一帖子可以有多个来源证据，而 resolved 表示可靠英文已胜出但差异仍有审计记录。

历史新帖 38 条均为英文；其中规范帖子层有 13 条可能截断。来源引文不会静默覆盖已经保存的可靠英文原文。

## 5. 月度覆盖

`corpus_coverage` 使用 UTC 自然月半开区间。数字只表示实际取得的来源记录，不表示该月全部 Tibo 发言数量，也不表示独立核验的 Reset 数量。

| UTC 月份 | AIPlanWatch | ModelYard | 状态 |
|---|---:|---:|---|
| 2025-09 至 2026-02 | 0 | 0 | 尚未取得；不能推断没有发帖或 Reset |
| 2026-03 | 6 | 0 | 部分资料 |
| 2026-04 | 6 | 0 | 部分资料 |
| 2026-05 | 3 | 0 | 部分资料 |
| 2026-06 | 5 | 0 | 部分资料 |
| 2026-07 | 12 | 0 | 部分资料 |
| 2026-08 | 10 | 20 | 部分资料，两个来源有重叠 |
| 2026-09（截至 cutoff） | 4 | 15 | 部分资料，非完整月份 |

主要缺口：目标窗口前半段没有可导入外部记录；两个来源都不是完整 Tibo 档案；回复上下文未取得；部分原帖目前只能依赖第三方引文；AIPlanWatch 是 Reset 历史页，其 46 条标签不能作为一般帖子分布样本。

## 6. Reset 核验与当前周期

导入前后的正式事件都保持为 4 个 Full Reset 加 1 个 Banked Special Reset。外部站点的 `Global Reset`、`Verified` 等标签仅保存在来源证据 metadata 中，没有自动创建事件。

- 最新 Full Reset 仍是 Tweet `2098685367058612394`，时间 `2026-09-12T08:09:17Z`，依据为 `post_time_proxy`。
- Banked 事件仍是紫色 Special Reset，不推进 Full Reset 周期。
- 补入更早资料后，当前周期没有倒退、没有负间隔、没有生成未来已完成事件。
- 正式候选当前为 0；证据不足的外部分类别没有被强行转成正式候选或事件。

## 7. 表达分析

实际分析见 [tibo-language-patterns.md](tibo-language-patterns.md)。目前有证据支持的六类观察是：

1. 明确动作、完成态和适用范围是最强信号。
2. `will land`、`by ...`、`tomorrow` 等未来时点有用，但时间可能修正。
3. reset button、庆祝、礼物和玩笑可以承载操作含义，但不能脱离上下文单独升色。
4. 里程碑是背景，不是确定性规则。
5. Banked Reset 必须与 Full Reset 分开。
6. 产品路线、功能征询和模型讨论是必要对照类，不能因 Codex 相关就推断 Reset。

有效样本只有 8 个。报告没有给出概率、覆盖率或可靠负样本比例，也没有把“未发现结果”写成“72 小时内没有 Reset”。

## 8. Judge 集成与受控验证

Judge prompt 已升级为 `v2-reset-judge-2`，每轮最多选择 6 个结果类型平衡的历史案例，并持久化 `corpus_version` 与实际 case IDs。历史回放会过滤 outcome 晚于 replay cutoff 的案例，避免偷看未来。

最终受控验证 judgement `#83`：

| 字段 | 结果 |
|---|---|
| Data Health | `HEALTHY` |
| 主等级 | `GREEN` |
| 24h / 48h / 72h | `GREEN / GREEN / YELLOW` |
| Prompt | `v2-reset-judge-2` |
| 历史案例 | `hist-2099393115241300166`, `hist-2098300998968357218`, `hist-2091412393368945027`, `hist-2090947196107764189`, `hist-2093811840258293947` |

结果正确区分了 Banked Special、显式未来预告、时间推迟和 `UNKNOWN` 产品讨论；历史完成事件只被当作类比与周期依据，没有被误认为当前红色信号。

首次加载新 prompt 的重启曾产生 `#81`（collector 尚未恢复，`STALE`）和 `#82`（健康恢复后）的连续调用。根因是 collector health transition 在首个异步 Judge 执行期间重新置脏。现已增加 70 秒启动合并窗口（覆盖一个 60 秒心跳周期）；最终重启实际记录为 `startup` + `collector_health_transition` 合并，只保存一个新 judgement `#83`，20 秒复查没有 `#84`。

## 9. 数据保护与验证

- 修改真实库前创建了在线一致性备份：`runtime/data/codex-reset-radar-v2.pre-monthly-coverage-20260917-103030.db`。
- 最终在线备份校验：`quick_check=ok`，外键违规 0。
- Schema version 4；没有清库、没有删除 V1 数据库。
- 导入重跑后帖子仍为 341、证据仍为 81、处理任务总数仍为 52 且 pending 为 0。
- `.env`、SQLite、日志、完整快照、构建目录均由 `.gitignore` 排除。
- 本轮没有 Git commit/push、Mirror/Pages、真实微信发送或新通知渠道接入。

## 10. 剩余盲点

1. 2025-09 至 2026-02 的目标窗口未取得外部资料。
2. 14 条第三方引文可能截断，所有外部记录均缺完整回复上下文。
3. ModelYard 的 direct/verified 标签没有逐条通过当前可读 X 页面再次独立确认。
4. 71 条中文存量中仍有浏览器翻译采集；后续只能在取得可靠原文时补证据，不能反向伪造。
5. 251 条较早 realtime 记录仍待分析，7 条失败记录仍需单独处置；本轮没有为追求数量无上限调用 DeepSeek。
