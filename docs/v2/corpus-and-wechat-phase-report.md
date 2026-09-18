# Codex Reset Radar V2 — 历史语料与微信选型阶段报告

## 1. 阶段结论

本阶段两条工作线均达到任务书要求的停止点：

- 历史语料已实际导入、可追溯、可幂等重跑，并已作为有限历史案例接入 DeepSeek Judge。
- 微信通知完成官方/供应商资料调研，但没有注册、绑定、购买、接入或发送真实消息。
- Backend、Web、Profile、Replies、Search 和 Intelligence Pipeline 在收尾时均正常运行。
- 未执行 Git commit/push、GitHub Mirror/Pages、Dashboard 重构或服务器部署。

## 2. 历史语料

### 已有记录

当前 V2 数据库共 341 条帖子：303 条 realtime、38 条 historical-only。处理状态为 38 `COMPLETED`、251 `PENDING`、7 `FAILED`、45 `HISTORICAL_UNANALYSED`。45 条中包括 38 条历史新帖和 7 条取得可靠英文后需要重新分析的既有记录。

### 新增外部记录

- ModelYard：35 条证据，首次导入新增 1、补全 24、冲突 10。
- AIPlanWatch：46 条证据，首次导入新增 37、补全 1、重复 3、冲突 5。
- 合计：81 条证据、38 条新 Tweet、25 条既有记录补全、15 条冲突证据。
- 幂等重跑：新增 0、补全 0；帖子和证据总数不变。

原文/翻译严格分离。现有语言盘点为英文 267、中文 71、未知 3；没有把中文反向翻译成英文原文。外部证据中 35 条为来源标记的 direct copy，46 条为第三方 quote；14 条 quote 可能截断，完整回复上下文仍未取得。

详细结果：[historical-corpus-report.md](corpus/historical-corpus-report.md)

## 3. 覆盖

- 目标范围：`2025-09-17T01:35:00Z` 至固定 cutoff `2026-09-17T01:35:00Z`。
- 实际取得范围：AIPlanWatch 约 2026-03-03 至 2026-09-12；ModelYard 约 2026-08-21 至 2026-09-14。
- 已生成 9 行按 UTC 自然月的 `corpus_coverage`，覆盖 2026-03 至 2026-09 的已取得资料。
- 主要缺口：2025-09 至 2026-02 无外部记录；2026-09 不是完整月份；全部来源都不能证明是完整 Tibo 档案。

因此本阶段不提供没有可靠分母的“覆盖率百分比”。没有取得记录不等于没有发帖或没有 Reset。

## 4. Reset

- 正式完整事件：4。
- 正式特殊事件：1（Banked，紫色）。
- 新增正式事件：0；外部站点分类没有自动升级。
- 当前最新 Full Reset：Tweet `2098685367058612394`，`2026-09-12T08:09:17Z`，`post_time_proxy`。
- 当前周期：保持正确，没有因较早历史导入倒退。
- 待核验正式候选：0；未充分核验的第三方声明仍停留在来源证据层。

## 5. 表达分析

已形成 6 类有证据支持的模式，使用 8 个有效案例：5 个 Full Reset 关联案例、1 个 Special Reset、2 个 `UNKNOWN` 对照。结论覆盖显式完成/范围、未来时间、玩笑/按钮/庆祝、里程碑、Banked 机制、产品讨论对照。

覆盖不足的结论已经明确：不能计算可靠预测概率，不能把关键词变成固定升色规则，不能把没有找到后续事件当作负样本，也不能把确认帖发布时间冒充精确后台执行时间。

详细分析：[tibo-language-patterns.md](corpus/tibo-language-patterns.md)

## 6. Judge 集成

- 语料版本：`corpus-20260917-b3e38dcf3bf4@2026-09-17T01:35:00Z`。
- Prompt：`v2-reset-judge-2`。
- 最终实际使用案例：`hist-2099393115241300166`、`hist-2098300998968357218`、`hist-2091412393368945027`、`hist-2090947196107764189`、`hist-2093811840258293947`。
- 真实调用：judgement `#83`，`HEALTHY`，主等级 `GREEN`，24/48/72h 为 `GREEN/GREEN/YELLOW`。
- 历史事件误触发：没有。Banked 被识别为 Special，`UNKNOWN` 产品讨论没有被当成正向 Reset 信号，过去的 Full Reset 没有被误报为当前事件。

启动期间的重复调用问题已经最小收敛：70 秒 startup gate 覆盖一个 collector 心跳周期并合并 health transition。最终重启只新增 `#83` 一次判断。

## 7. 微信调研

### 主路线候选

长期候选是经认证的微信服务号，使用符合账号服务类目的已批准模板/服务通知能力。成立条件包括：合格主体、认证、合规模板批准、公开 HTTPS 回调和真实手机送达验证。当前没有证据证明本项目一定能获批相应模板，因此结论仍是：**尚无已验证、满足全部条件的主方案**。

### 当前个人候选

PushPlus 一对一是当前本地阶段最容易继续验证的候选；Server酱 Turbo 是个人备选。两者的 API 接受、微信内入口、正文可见性和手机系统通知仍需要下一阶段在一台真实手机上分别验证。

### WxPusher 备选

WxPusher 保持固定备选，不恢复为默认主渠道。标准应用具备 UID/topic 多用户能力和发送记录查询；但其当前微信 iLink/ClawBot 路径存在 10 条/24 小时后需要用户重新互动的限制，不符合“不依赖每天手工激活”的主路线要求。

### 主要未验证项

- 服务号的主体资格与本项目通知模板能否获批。
- 小程序永久订阅模板是否适用于不定期 Reset 提醒。
- PushPlus、Server酱和 WxPusher 各具体渠道的手机系统通知表现。
- Server酱集中多用户订阅能力和付费口径。
- 多供应商是否共享同一下游微信故障域。

真实发送：**未执行**。

完整证据与 1/100/1,000 用户容量比较见 [wechat-channel-research.md](notifications/wechat-channel-research.md)。

## 8. 回归与数据安全

| 项目 | 结果 |
|---|---|
| Backend | 24 passed |
| Web | 6 passed；typecheck PASS；production build PASS |
| Collector Extension | 12 passed；typecheck PASS；production build PASS |
| SQLite | 在线备份 `quick_check=ok`；外键违规 0 |
| HTTP | Backend 4 个 API、Web 首页及 2 个代理 API 均为 200 |
| Web 数据源 | 只读 localhost `/api/v2/*`；无 GitHub Raw/public-data 引用 |
| Git diff | `git diff --check` PASS（仅已有 LF/CRLF 提示） |
| Secret 扫描 | 源码/文档与两个 dist 未发现 Key、Token 或私钥特征 |
| 忽略规则 | `.env`、SQLite、日志、完整 corpus snapshot、临时校验库均被忽略 |

历史导入专项还验证了同批重跑、多来源合并、英文原文优先、冲突保留、保守回滚、回放不偷看未来、Special/Unknown 区分和 Judge case 版本化。

## 9. 当前运行

收尾时：

- Backend：`http://127.0.0.1:8787`，PID 1576，版本 `2.0.0-alpha.2`，healthy。
- Web：`http://127.0.0.1:5173`，PID 20312，保持运行。
- Profile / Replies / Search Backfill：全部 healthy。
- Pipeline / Judge：ready，pending jobs 0。
- GitHub Mirror / Pages：disabled。

本阶段为加载新代码执行过一次正常工作流重启，只使用根目录 `stop-v2-local.bat` 和 `start-v2-local.bat`；没有启动 legacy/v1 Backend。任务结束后不停止服务。

## 10. Git 与变更范围

本轮新增/修改的主要范围：

- 历史语料 schema、来源证据、batch/change/case/coverage 模型；
- 历史导入器、幂等/回滚/覆盖测试；
- Judge 历史案例检索、prompt/context/version 持久化；
- startup Judge 合并窗口；
- 语料策略、来源、表达分析、微信选型和阶段报告。

工作树同时保留此前尚未提交的 Alpha 2 Backend/Web/Collector 成果；本轮没有覆盖、reset 或丢弃这些变更。没有 commit/push，也没有把真实数据库、完整语料、日志、`.env`、Token、Cookie 或 UID 纳入 Git。

## 11. 停止点

本阶段在此停止。下一步需要产品经理/用户先选择微信验证路线，再单独下达真实账号绑定和通知接入任务；历史工作线不再等待微信选型。
