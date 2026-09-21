# Judge 契约、采集健康与回复预告修复

日期：2026-09-21。整体：**PARTIAL**。代码修复、隔离回归、真实 Backend / API 联调已完成；Profile / Replies 的实际恢复、各三次持续心跳和视觉验收未完成，不能标记全链路 PASS。

## 1. 基线、保护与版本

- 基线：`2.0.0-alpha.4`，原提交 `53575d0c64525b778dea28ebb919f8d9b1138e98`，原运行指纹 `c9721c73c737ef2b`。
- 独立工作分支：`fix/judge-context-health-20260921`。
- 正式代码提交：`2cae1dea781e2e7f217beb0bd2ef69675334a9f8`。
- 本地提交包含尚未提交但为本轮依赖的父帖正式模块与回归；未混入启动器修改、微信任务文档或临时资产。原先启动器修改和历史报告仍保留。
- 运行标签仍为 Alpha 4 加本地修复，未假造新发布标签；实际源码以提交及指纹识别。
- 修复分支尚未推送，远端 main 未更改，远端 CI 未触发，旧标签未移动。未将部分验收版本发布为正式通过。
- 一致性备份：`D:\work\20260828-CodexResetRadar\runtime\judge-health-fix-20260921\before.db`，完整性 ok、外键错误 0。
- 限量故障证据：同目录 `before.json`，包含原数据库 Judge、规范读取、输入版本、当前版本、任务分类及主动恢复前的健康状态。没有读取整份大型日志或导出 Cookie。

## 2. 直接根因与修复

原 `latest_judgement()` 已把 SQL `raw_json` 解码成内部 `raw`，校验却继续读取 `raw_json`，因此真实引用受上下文管理回复的合法 Judge 被误拒。

新增测试在改代码前实际失败于 `judgement_is_usable()`，完整路径为：写入数据库 raw_json → 正式读取 → 内部 raw → 校验 → Radar API。不是直接手造一个原始字典冒充端到端回归。

现在唯一边界 `normalize_judgement()` 负责 SQL JSON 解码，内部校验只接受规范 raw；JSON 损坏、类型错误、双表示冲突等返回明确 CONTRACT_ERROR，不把坏资料静默变为空字典。

`validate_judgement()` 返回 valid / reason，覆盖：

- 过期、未来判断时间、非法时间或等级；
- 当前周期改变；
- 引用不存在、被内容政策禁用；
- 管理回复缺输入版本，输入版本类型不符或清单不完整；
- 目标正文、直接父帖和实际祖先的语义版本变化。

新 Judge 同时记录 input_versions 和 input_post_ids。旧 Judge 原文、颜色、生成时间、有效期没有回写，未清空引用，也没有重新激活 Judge 229。真实最终验证使用新 Judge 231。

## 3. 状态与健康分开

Radar 新增 validation、current_data_health、judgement_data_health、display_mode、last_known_result，保留现有 judge_runtime / pipeline。

| 情况 | 展示行为 |
| --- | --- |
| 尚无 Judge | 明确“尚未生成判断” |
| 已有结果但结构或校验错误 | 显示校验原因，不谎称没生成结果 |
| 正文 / 父帖 / 周期变化 | 旧结果失效，等待重判 |
| 已过有效期 | 过期，白色行动区 |
| 结果合法但生成时或当前采集 STALE | 当前行动区白色；单独折叠展示最后已知模型结果，不作为行动建议 |
| 新鲜、合法，模型输出 UNKNOWN | 保留模型真实理由，display_mode=model_unknown |
| 新请求失败 | 显示运行错误；旧结果仍独立接受有效期和版本检查 |

刷新 Backend 失败时不继续把缓存颜色当作当前行动建议。界面复用原布局及紫色样式，并提供文字状态，不仅依靠颜色；这是 ui-ux-pro-max 技能对本轮的有限影响，没有重新设计 Dashboard。

## 4. 采集现状与未完成部分

恢复前 Profile / Replies 最后心跳均为北京时间 **2026-09-20 16:27:04**，旧实例分别为 `profile-cs-c4811530-7969-43e8-bf9d-5d7a1d76bf80`、`replies-cs-f3da3d44-60f6-4b68-9394-25cf990bb04c`。Search 在检查前仍有新上报。不能把这些旧 healthy 当作持续运行。

新的 `collector_health()` 是健康 API、Judge 和 Radar 唯一共用的新鲜度计算。阈值保持 **15 分钟**；返回 reported_state、派生 state、last_seen_at、age_seconds、checked_at、reason。历史补传保留客户端 observed_at，不把接收时间伪装为观察时间；早于当前记录的心跳和明显超前时钟被拒绝。无观察时间的兼容心跳采用服务器接收时间，不能用于证明旧内容脚本持续存活。

GET 接口只读；时间推进自然变 STALE；收到真实新心跳恢复后，状态转换合并请求新 Judge，旧 Judge 的生成时健康不改写。

本轮工具检查到 Edge 仍在运行，窗口标题含 Dashboard 和另外 6 个页面。但浏览器接口返回 `nodeRepl.fetch request failed`；computer-use 无法可靠确认浏览器 URL，停止了浏览器操作。未能读取具体 Profile/Replies URL、页面登录状态或诊断环形缓冲，未确认断连根因，不将其归咎于用户未刷新或 Edge 冻结。

已一次性请求用户刷新现有两页：

- `https://x.com/thsottiaux`
- `https://x.com/thsottiaux/with_replies`

本轮没有改扩展代码，因此不要求再次重载扩展。既有构建目录为 `D:\work\20260828-CodexResetRadar\apps\collector-extension\dist`，version_name 为 `2.0.0-alpha.4+reply-context.1`。不能仅凭磁盘构建号宣称已核实浏览器实际加载目录。

尚未完成两路各三次有正常时间跨度的新心跳，以及各一次真实扫描。不能用旧缓冲集中补传代替。Search 单独记录于最终本地回执，不能代替这两路恢复。

## 5. 有界调度

- 最大合并等待集中定义为 **60 秒**，短去抖 3 秒，从第一次 dirty 开始；重复请求不延后起点。
- 只有近期实时、正在执行或已经到期可执行的任务可以短暂阻挡；远期重试、终止失败及历史任务不形成整体屏障。
- 超时使用当前通过输入版本和内容检查的分析，pending_inputs 明示未完成 / 延后 / 失败资料，不拿它们当“无信号”证据。
- 没有可用帖子则记录 NO_USABLE_POSTS 及恢复安排，不制造 Judge，也不无限等待队列清零。
- asyncio 锁保障 single-flight；在途出现变化保留 dirty，响应返回时检查输入、周期和事件快照，迟到旧结果不落库覆盖新状态。
- 不是每 60 秒无条件调用。新增通用显式 reprocess / judge request 接口复用同一任务和模型流程，不另建分析器。

## 6. Banked 案例与特殊预告

目标回复 `2101352781219258527`，父帖 `2101093319501664368`，父作者 `udiWertheimer`。实际父帖在索要 banked reset，Tibo 表示“OK fine”并提及周二；原始父帖和回复保存在本地库，本报告不复制完整正文。

原 Judge 230 一面认定日期指代不明，一面仅因覆盖周二而提高完整 Reset 的长窗口等级，是已观察到的边界矛盾。因此只对现有 Judge Prompt 添加通用规则：时间校准必须有独立的完整 Reset 动作依据；特殊发卡对话中的模糊代词不能擅自拆成第二个完整 Reset 承诺。没有写固定颜色、真实 Tweet ID 或改动人工裁定。

- 分析 Prompt 保持 `v2-post-semantics-9-context`，翻译保持 `v2-zh-translation-2-context`。
- Judge Prompt 升为 `v2-reset-judge-8-context-health`。
- 目标回复通过正式 reprocess 接口重新进入任务，任务 1041 于 17:50:49 完成；相同输入命中已有分析 / 翻译缓存，真实分析和翻译新增调用为 0。
- 候选 3 仍为 BANKED / announced / NEEDS_REVIEW；候选 4 保留日期指代不明。未创建假完成事件。
- 新增独立 `special_announcements` 只读视图：近期 7 天内、当前版本可用、身份明确的 Banked / reset-card 预告；排除取消、超期、已形成正式事件、受限制和失效输入。
- 标签为“重置卡相关预告 · 待核验 / 尚未确认发放”，复用紫色。日期不明时 scheduled_at=null，不显示确定周二日程。采集过期时标为最后已知信息。

## 7. 新的真实 Judge 与调用记录

新 Judge **231**：

- 判断时间：北京时间 2026-09-21 **17:51:20**；完成 17:51:34；有效至 **19:51:20**。
- 实际模型：deepseek-v4-flash；Prompt：v2-reset-judge-8-context-health。
- 校验：VALID；输入版本数 **24**。17:58 再次只读核验，Backend 与 Web 代理均返回 Judge 231、VALID、last_known；生成时和当前数据健康均为 STALE。
- 原始结果：主等级 GREEN，24h GREEN，48h GREEN，72h YELLOW；理由没有再将模糊周二视作完整 Reset 的独立升色依据。
- 生成时健康为 STALE，所以这组颜色不是当前行动建议。当前 API 正确保留白色 UNKNOWN，display_mode=last_known。

启动、显式代表性重处理、处理完成及一次手动当前 Judge 请求合并为 **一次真实 Judge 逻辑调用、一次 Provider 请求，成功且无重试**。触发来源保存在 raw.triggers 及有界日志。没有重复调用直到得到预期颜色；一条成功结果也不能证明模型从此不会误判。

## 8. 回归与运行验收

| 项目 | 结果 |
| --- | --- |
| Backend | 89 项通过，含 Judge 数据库契约、损坏输入、时间 / 版本 / 内容限制、健康衰减、队列有界等待、single-flight、迟到响应、预告过滤 |
| 干净正式源码副本 Backend | 同为 89 项通过，不依赖忽略目录中的补录模块；使用既有解释器依赖，不声称重新安装所有依赖 |
| Web | 7 项通过；类型检查、构建通过 |
| Collector | 18 项通过；类型检查、构建通过；本轮没有修改采集器实现 |
| Secret / 大文件 / 私有资产检查 | 本次显式暂存 21 个文件无发现；未包含数据库、完整语料、密钥或日志 |
| 通知 | 微信 0，邮件 0；没有接入任何自动通知路径或调用 live 测试入口 |
| 实际页面 | 待核验；已验证 Web 代理 API，不冒称已观察渲染 |

最终加载指纹：`c9b1fd210a8ee0e1`。Backend PID 20688，Web PID 7240，均由项目安全停启入口启动并保持运行；没有关闭 Edge 或其他项目进程。

数据库、事件 / 周期前后比较、输入哈希、API / Web 对照、有限调用日志和最新心跳在本地 `acceptance.json`。生产没有全库重跑，没有批量删除或改写旧 Judge。

17:55:50 的验收快照记录：帖子 397、分析 238、正式事件 14、周期 13、候选 3，均与备份一致；Judge 从 230 增至 231。事件和周期逐行比较不变，数据库 integrity_check=ok、外键错误 0。17:58:35 只读复核时，Search 最新新心跳为北京时间 17:58:35，派生状态 FRESH；Profile / Replies 重启后尚无新心跳（NO_HEARTBEAT），不能宣称三路恢复。Backend 和 Web 代理结果一致，两个服务进程仍在运行。

## 9. 本地材料与停止边界

材料目录：`D:\work\20260828-CodexResetRadar\runtime\judge-health-fix-20260921\`，被 Git 忽略：

- `before.db`：一致性备份。
- `before.json`：故障现场。
- `acceptance.json`：最终运行与核验回执。

临时正式源码副本位于 `D:\work\20260828-CodexResetRadar\_tmp\judge-health-clean-20260921`。验证后已尝试清理，但删除命令被执行环境策略拒绝，未改用其他方式绕过；副本不含生产资产，不是程序运行依赖，仍留本地。

剩余限制：两路采集恢复未获实测证据；三次持续心跳 / 扫描和视觉验收未完成；原有 3 个父帖失败任务保留，不扩大为全库补抓；此次语义结果来自一次真实调用，不是长期准确率证明。等待刷新后沿同一服务继续验收，不需再写任务书。
