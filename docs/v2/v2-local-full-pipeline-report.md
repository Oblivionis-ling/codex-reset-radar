# Codex Reset Radar V2 本地完整业务链路报告

## 1. 结论

截至 2026-09-14 20:06（Asia/Shanghai），V2 本地完整业务链路已经实际接通并保持运行：

```text
真实 X 页面
→ V2 Collector Extension
→ V2 Backend 去重入库
→ 持久处理任务
→ DeepSeek V4 Flash 分析 / 翻译
→ Reset 事件归一化
→ DeepSeek Judge
→ /api/v2/*
→ 本地 Dashboard
```

运行版本为 `2.0.0-alpha.2`。Backend、处理流水线、Judge、Profile、Replies、Search Backfill 均为 healthy/ready；GitHub Mirror、Pages 和真实通知均未启用。本轮没有写入假 Tweet、假 Reset、假预警或固定颜色。

## 2. 当前运行现场

| 项目 | 实际状态 |
|---|---|
| Backend | `http://127.0.0.1:8787/`，PID `15816`，healthy |
| Web | `http://127.0.0.1:5173/`，PID `9040`，运行中 |
| API 版本 | `2.0.0-alpha.2` |
| 数据库 | ready，278 条真实帖子 |
| Intelligence Pipeline | ready，`deepseek-v4-flash` |
| Judge | ready，最新 judgement `#5` |
| 待处理任务 | 0 |
| Profile | healthy，20:05:33（UTC+8），sequence 442 |
| Replies | healthy，20:05:33（UTC+8），sequence 438 |
| Search Backfill | healthy，20:04:38（UTC+8） |
| GitHub Mirror / Pages | disabled / false |

进程记录确认两项服务都属于 `D:\work\20260828-CodexResetRadar`，且由项目规定的 `start-v2-local.bat` 工作流记录；没有启动 legacy/v1 Backend。任务结束后不调用停止脚本。

## 3. 已启用的业务处理

- Collector 接收 Profile、Replies、Search 三路真实页面数据并写入 SQLite。
- 入库区分 `new`、`updated`、`duplicate`；完全重复 sighting 不进入模型任务。
- 内容哈希、分析提示词版本、翻译提示词版本和模型共同构成处理身份。
- 新增或实质更新先持久化，再由后台任务执行分析、翻译、事件识别和重判。
- 处理任务可失败重试并在重启后恢复，模型调用不占用采集请求的数据库事务。
- Full Reset 与 Special Reset 分开；Special Reset 固定显示为 PURPLE，不开启完整周期。
- Judge 支持新内容、事件/健康变化触发与每小时自动重判。
- Web 每 60 秒读取本地 `/api/v2/*`；刷新失败时保留最后一次成功数据并显示错误。

## 4. 一条真实 Tweet 的完整时间线

验收帖子：[`2099393115241300166`](https://x.com/thsottiaux/status/2099393115241300166)

该记录是 X 上的真实 Tibo 帖子。本轮属于“已有真实帖子首次进入 Alpha 2 业务处理”，不是伪造数据，也不宣称为 Alpha 2 启用后的新帖秒级发现。

| UTC 时间 | 阶段 | 证据 / 结果 |
|---|---|---|
| 2026-09-14 07:01:38 | X 发帖 | Tweet ID `2099393115241300166` |
| 07:13:05.175 | V2 入库 | `tibo_posts.id=711`；同时间采集日志记录 4 条真实记录 accepted |
| 09:49:38.525 | 处理排队 | `processing_jobs.id=4`，`POST_PROCESSING`，持久任务已创建 |
| 09:49:38.774 | DeepSeek 分析开始 | `operation=post_analysis`，模型 `deepseek-v4-flash` |
| 09:49:43.147 | 分析保存 | `post_analysis.id=4`，分类 `codex_related`；结论为功能反馈征询，与额度 Reset 无关 |
| 09:49:43.163 | 翻译步骤完成 | 采集内容已是中文，保留原采集文本并完成翻译状态，不进行无意义的再次翻译 |
| 09:49:43.172 | 任务完成 / 请求重判 | `POST_PROCESSING_COMPLETED`，`job_id=4`；触发 `post_processed` Judge 请求 |
| 09:52:31.330 | 首次成功 Judge | judgement `#1` 保存，证据包含该 Tweet ID |
| 11:56:56.542 | 自动小时重判 | judgement `#5` 保存，仍引用该 Tweet ID；证明不是一次性手工脚本 |
| 12:06:02 | API 验收 | `/api/v2/posts` 返回完成的分析；`/api/v2/radar` 返回 judgement `#5` |

真实 DeepSeek 翻译调用另由 Tweet `2099393997026582791` 验证：英文 `lol` 的分析于 09:49:42 保存，`post_translation` 随后真实调用 `deepseek-v4-flash`，09:49:43 成功保存中文“哈哈”。

## 5. 入库、重复采集与自动任务

- 数据库总数为 278；上一轮联调已记录从 277 增至 278 的真实新增。
- Alpha 2 验收期间没有为了测试等待或制造新帖，故帖子总数保持 278。
- Profile / Replies 持续每分钟提交真实页面批次。20:05 前后的代表性批次均为 `new=0`、`updated=0`、`duplicate>0`、`queued=0`。
- 重复页面采集只更新 sighting/健康信息，不重复创建分析任务或调用 DeepSeek。
- 当前共有 21 个持久处理任务记录，全部 `COMPLETED`；pending jobs 为 0。
- 278 条帖子中有 21 条完成 Alpha 2 目标范围内的分析和翻译，257 条较早存量仍为 PENDING。本轮按任务书只补处理近期、页面展示和 Reset 证据相关记录，没有对全部历史做昂贵的无差别重分析。

## 6. Reset 历史与周期

当前正式事件共 5 个：4 个 Full Reset、1 个 Special Reset；候选为 0。

### 最近一次完整 Reset

- 事件：`FULL_RESET #1`
- 证据 Tweet：[`2098685367058612394`](https://x.com/thsottiaux/status/2098685367058612394)
- 事件时间：2026-09-12 08:09:17 UTC（发帖时间代理）
- 标题：额度重置已全部传播完成
- 范围：`all_paid`
- 执行阶段：`completed`
- 时间依据：`post_time_proxy`，系统没有伪造更精确的实际执行分钟

默认参考时间按“最近完整 Reset + 7 天”计算为：

```text
2026-09-19 08:09:17 UTC
2026-09-19 16:09:17 Asia/Shanghai
```

### 特殊事件

- `SPECIAL_RESET #2`
- 类型：`BANKED`
- 证据 Tweet：`2090964822422949999`
- 显示：PURPLE
- 不修改最近完整 Reset，也不打开新的完整周期

### 事件合并

Tweet `2094251180121854309` 与 `2094252447271366730` 被归并为同一 Full Reset 事件，证据时间范围为 2026-08-31 02:29:25–02:34:27 UTC，没有因两条报道重复创建事件。

## 7. 最新真实 DeepSeek Judge

最新 judgement：`#5`

| 字段 | 实际结果 |
|---|---|
| 主行动等级 | GREEN — 正常使用 |
| 24 小时 | GREEN |
| 48 小时 | GREEN |
| 72 小时 | YELLOW |
| Data Health | HEALTHY |
| 模型 | `deepseek-v4-flash` |
| Prompt | `v2-reset-judge-1` |
| 判断时间 | 2026-09-14 11:56:51 UTC |
| 当前信号预计时间 | 2026-09-19 08:09:17 UTC |

理由摘要：最近一次完整 Reset 在 9 月 12 日；此后没有新增帖子给出临近 Reset 的前瞻信号，现有内容为功能征询、修复承诺与闲聊。按七天节奏外推的 9 月 19 日参考点不在 24/48 小时窗口内，72 小时进入关注范围。

证据 Tweet ID：

- `2098685367058612394`
- `2099393115241300166`
- `2099394367744356554`
- `2098612714704891959`

Judge 首次实跑时曾有 3 次输出一致性校验失败，系统没有保存非法结果。后续按启动恢复流程重新请求并成功保存 judgement `#1`；之后健康变化与两轮小时调度继续产生 `#2`–`#5`。这验证了“失败不伪造颜色、后续可以恢复”的真实运行行为。

## 8. API 与 Dashboard 验收

以下请求均实际返回 HTTP 200：

- `GET http://127.0.0.1:8787/api/v2/health`
- `GET http://127.0.0.1:8787/api/v2/radar`
- `GET http://127.0.0.1:8787/api/v2/posts`
- `GET http://127.0.0.1:8787/api/v2/resets`
- `GET http://127.0.0.1:5173/api/v2/health`
- `GET http://127.0.0.1:5173/api/v2/radar`

Web 使用相对地址 `/api/v2` 和 Vite 本地代理，不请求 GitHub Raw 数据。

用户提供的 Edge 页面截图确认本地 `127.0.0.1:5173/#/` 已实际显示：

- V2 Alpha 2；
- GREEN 主行动等级和“正常使用”；
- 默认参考时间 2026-09-19 16:09:17（UTC+8）；
- 当前信号窗口和真实 Judge 依据；
- 24h / 48h / 72h 分级区域。

截图同时暴露了完整 `estimate_basis` 撑高首屏的问题。现已做最小 UI 修正：首屏只显示第一句摘要，完整依据保留在默认折叠的 `<details>` 中；中文句号后没有空格时也能正确截断。折叠入口具备 44px 点击区域、键盘焦点样式和长文本换行。Vite 开发服务会热更新当前页面。

UI 修正遵循渐进披露和长文本不溢出的交付规则，没有换主题或重做布局。Web 自动化已验证摘要截断；原始截图是修正前的浏览器验收证据，未伪装为修正后的新截图。

页面业务字段已经来自真实 API，不再是 UNKNOWN 占位。若模型尚未就绪、失败或过期，前端会显示对应状态；若刷新失败，则保留最后成功数据而不是白屏或清空页面。

## 9. 自动化和回归测试

| 组件 | 结果 |
|---|---|
| Backend | 16 passed |
| Web | 6 passed；typecheck PASS；production build PASS |
| Collector Extension | 12 passed；typecheck PASS；production build PASS |
| `git diff --check` | PASS |
| 凭据扫描 | 变更及新增源码未发现 DeepSeek/OpenAI 风格 Key、GitHub Token、WxPusher Token 或私钥内容 |

测试覆盖包括：

- 新帖自动进入处理；
- 重复 sighting 不重复调用模型；
- 模型失败不丢帖子；
- 翻译失败不擦除已经完成的分析；
- Full Reset 周期切换；
- Special Reset 不改变完整周期；
- 旧事件回填不倒退当前周期；
- 近时间窗口多条证据合并；
- 浏览器中文翻译不覆盖已经保存的英文原文；
- 默认参考日期过期时不向未来滚动造假；
- 五种前端等级、PURPLE Special Reset、无 confidence 字段；
- SPA status 路由返回 Profile / Replies 时的采集上下文；
- 长 Judge 依据的首屏渐进披露。

## 10. 数据保护与安全

- 生产数据库修改前已创建备份：`runtime/backups/codex-reset-radar-v2-pre-alpha2-20260914T094916Z.db`。
- 备份包含 278 条帖子，SQLite `quick_check=ok`。
- Schema 以向后兼容方式升级到 version 3，没有清库或重新导入 V1。
- `.env`、数据库、日志、PID、备份、构建产物和 `_tmp` 均被 `.gitignore` 排除。
- `.env.example` 只包含空白凭据占位，不含 Secret。
- 本轮未执行 Git commit、push、Mirror 或 Pages 发布。

## 11. 已知限制与剩余盲点

1. 部分近期帖子在 Edge 已将 X 页面翻译为中文后才进入 V2，因此数据库只能如实保留当时采集到的中文，不能反向伪造其英文原文。代码已经阻止未来中文 sighting 覆盖数据库中已经存在的英文原文；要保存新的英文原文，需要浏览器采集时关闭页面自动翻译。
2. 最新 Judge 的 `estimate_basis` 很长，模型返回文本末尾停在半句；`reason_summary`、等级、证据和预计时间均完整且通过校验。Dashboard 现在首屏展示完整的第一句摘要，并把模型原始长依据保留在折叠区。此项不阻断当前判断，但后续可在不改变结论的前提下继续收紧模型输出长度约束。
3. 257 条较早存量帖子尚未逐条执行 Alpha 2 语义分析；它们不在本轮近期/页面/Reset 证据补处理范围内。当前 21 条目标记录、5 个正式事件和当前 Judge 已完成。
4. 没有为了验收等待 Tibo 发布新帖。本轮用真实存量帖的首次 Alpha 2 处理和持续真实重复采集证明链路；不能将其表述为“新帖秒级发现”。

## 12. 最终状态

```text
采集：PASS — Profile / Replies / Search 三路真实请求持续到达

入库与去重：PASS — 278 条；重复批次 new=0 / updated=0 / duplicate>0 / queued=0

分析：PASS — 21 条真实记录完成；示例 analysis #4

翻译：PASS（带历史原文盲点）— 实际 DeepSeek 翻译调用成功；已采到中文的帖子不能伪造英文

Reset 事件处理：PASS — 5 个真实正式事件；4 Full + 1 Special；近重复证据已合并

DeepSeek Judge：PASS — 真实 deepseek-v4-flash 调用；最新 judgement #5

下一次时间：2026-09-19 08:09:17 UTC / 16:09:17 UTC+8，按最近完整 Reset + 7 天估算

主预警：GREEN，判断时间 2026-09-14 11:56:51 UTC

24h / 48h / 72h：GREEN / GREEN / YELLOW

Dashboard：PASS — 已在 Edge 显示真实 API 数据；首屏长依据问题已最小修正

自动处理：PASS — 持久任务、启动恢复、事件触发、健康触发和每小时重判均已验证

前端地址：http://127.0.0.1:5173/

后端地址：http://127.0.0.1:8787/

服务：保持运行
```
