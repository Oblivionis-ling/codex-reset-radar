# Codex Reset Radar 项目目录与文档整理报告

盘点日期：2026-09-21。根目录：`D:\work\20260828-CodexResetRadar`。

本报告用于决定后续空间整理，不执行整理。基于实际目录、Git 跟踪状态、文档标题与内容抽查、启动说明和源码入口；不是全量代码审计，也不是删除授权。未读取或展示 `.env` 的秘密值，未运行模型或发送通知。

统计为写入本报告之前的快照：`docs/` **87 个文件，其中 73 个 Markdown，约 3.34 MiB**；Git 跟踪 docs 文件 83 个，另外 3 个未跟踪任务/报告及 1 张忽略图片。本报告新增后 Markdown 数加 1。第三方依赖自带的 README/LICENSE、缓存副本中的重复文档不逐份解释；项目自己维护的文档和本地审核文字材料列在下文。

## 1. 先看结论

1. **现用源码只有 apps 下的三个应用**：Backend、Web、Collector。根目录同名旧目录不等于第二套现用系统。
2. **不能直接删根目录 backend**：其中 `.venv` 仍是启动器的有效 Python 环境回退；`data` 保存旧 V1 数据。
3. **文档的主要问题是“当前规范与历史状态混读”，不是体积太大**。V1 已集中在 docs/v1；V2 阶段报告、语料过程证据仍与规范相邻。
4. **最大空间来自 V1 数据，而非文档**：backend/data 约 3007 MiB，含约 1232 MiB 数据库和大体积旧日志。应单独制定保留策略，不能凭“旧”就删除。
5. **资料包与报告不是重复备份**：data/corpus 保存输入、人工裁定和已审版本；runtime/review 保存程序实际回放输出。两者承担不同证据职责。
6. 建议先整理索引和文档标识，再评估旧构建与临时副本，最后才处理历史数据；本轮保持所有内容原位。

## 2. 实际目录分级

```text
项目根目录
├─ README.md / VERSION / .env.example     总入口、统一版本、配置模板
├─ .env                                  本地秘密配置，禁止提交或抄入报告
├─ start-v2-local.bat / stop-v2-local.bat  正常启停入口
├─ test-notifications.bat                 手动通知测试入口
├─ apps/
│  ├─ backend/
│  │  ├─ app/                            当前 V2 后端、模型和业务代码
│  │  │  └─ notifications/               独立通知准备代码，未接自动 Judge
│  │  ├─ tests/                          正式后端回归
│  │  └─ legacy_v1/                      旧后端源码与测试存档，不是当前入口
│  ├─ web/                               当前本地 Dashboard
│  │  ├─ src/                            页面/API/样式/测试
│  │  └─ node_modules/、dist/             依赖与构建产物
│  └─ collector-extension/               当前浏览器扩展
│     ├─ src/                            Profile/Replies/Search 与父帖补全
│     └─ node_modules/、dist/             依赖及供浏览器加载的构建
├─ scripts/                              当前启停、测试、迁移、标准语料工具
├─ docs/
│  ├─ v2/                                当前 V2 规范 + 早期 V2 报告
│  │  ├─ corpus/                         语料规范、审核流程和历史结项证据
│  │  └─ notifications/                  早期微信调研，不是当前操作指南
│  ├─ notifications/                     当前通知说明和用户测试指南
│  ├─ maintenance/                       本轮及近期维护报告
│  ├─ v1/                                V1 文档归档
│  │  ├─ archive/                        旧 Pages workflow 文本存档
│  │  └─ public-data-snapshot/            旧公开 JSON 示例快照
│  ├─ phase-g-screenshots/                旧界面截图
│  └─ notification_preparation_and_workspace_cleanup.md  用户任务原件
├─ runtime/                              V2 本地运行与验收资产（默认忽略）
│  ├─ data/                              当前数据库及相关本地数据库
│  ├─ logs/、launcher/、pids/             业务日志、启动日志/记录、进程归属
│  ├─ backups/                           备份
│  ├─ review/                            历史隔离回放
│  ├─ reply-context-fix/                 父帖修复证据
│  ├─ judge-health-fix-20260921/          本轮备份、故障和恢复验收证据
│  └─ notification-tests/                通知离线/测试记录
├─ data/
│  ├─ corpus/imports/                    历史导入资料
│  ├─ corpus/reviews/                    冻结语料、GPT 参考、人工裁定、已审包
│  └─ analysis/                          分析产物保留位置
├─ backend/                              旧根目录残留：Python 环境 + V1 数据
├─ dashboard/                            旧前端 node_modules、dist
├─ extension/                            旧扩展 node_modules、dist
├─ legacy/v1/                            旧启动器、镜像和运维脚本存档
├─ local-archive/20260919-historical-tools/ 一次性补录工具，本地保留
├─ _tmp/                                 历史临时 worktree/源码副本/小数据库
├─ .github/workflows/ci.yml               三应用测试与构建 CI
├─ .git/                                 Git 历史与工作树元数据
└─ .pytest_cache/                        可重建测试缓存
```

### 目录大小与整理属性

数字按文件逻辑长度求和，包含隐藏/忽略文件，不等于 NTFS 实际占用或确定可释放量；运行中的文件可能增长。

| 目录 | 文件数 | MiB | 属性及整理建议 |
| --- | ---: | ---: | --- |
| apps | 3542 | 115.39 | 正式源码与当前依赖；内部区分 legacy、dist 和 node_modules |
| backend | 3702 | 3069.66 | 最大项；不能整体删除，环境仍有启动依赖 |
| dashboard | 899 | 49.71 | 旧依赖/构建，核实无引用后可单独处理 |
| extension | 2556 | 63.53 | 旧依赖/构建，先核实 Edge 实际加载路径 |
| data | 115 | 10.39 | 语料、人工裁定、历史资产；保留 |
| docs | 87 | 3.34 | 整理以可读性为目标，删除省不了多少空间 |
| runtime | 183 | 78.15 | 当前数据、备份、日志和回放；按子目录制定策略 |
| _tmp | 658 | 13.58 | 清理候选，不能不分用途整目录清空 |
| local-archive | 7 | 0.09 | 一次性工具来源留存；节省空间无意义 |
| legacy | 8 | 0.07 | 历史脚本留存，无必要为体积删除 |
| scripts | 22 | 0.16 | 正式工具及缓存，保留有效入口 |
| .git | 242 | 3.79 | 版本历史，禁止手工清理内部对象 |
| .github | 1 | <0.01 | 当前 CI |
| .pytest_cache | 6 | 0.02 | 可再生缓存，不是主要空间来源 |

backend 细分：`.venv` 62.49 MiB；`data` 3007.18 MiB。后者最大几项：
- `radar.db`：1232.18 MiB，V1 数据库，不是当前 V2 库。
- `observability/events/backend-events-legacy-2026-09-08.jsonl`：1046.48 MiB。
- `observability/events/backend-2026-09-08.jsonl`：246.81 MiB。
- `observability/events/backend-2026-09-09.jsonl`：147.18 MiB。
- 同日带后缀的 legacy 事件日志：65.11 MiB。

这些是**待制定归档保留策略的资产**，不是已经确认可删的垃圾。移到同磁盘 archive 也不会释放空间。

## 3. 当前应从哪份文档进入

| 想了解什么 | 权威入口 |
| --- | --- |
| 项目全貌和常用链接 | README.md |
| 安装、启动、停止、测试 | docs/v2/local-development.md |
| 系统架构 | docs/v2/architecture.md |
| 等级与 Reset 产品含义 | docs/v2/product-model.md |
| 数据库/API | docs/v2/data-model.md、api-contract.md |
| 统一语料格式及内容边界 | docs/v2/corpus/corpus-standard.md、data-policy.md |
| 语料阶段最终结论 | docs/v2/corpus/corpus-closeout-report.md |
| 微信/邮件如何手动测试 | docs/notifications/testing-guide.md |
| 通知渠道实现和契约 | docs/notifications/README.md |
| 最近 UNKNOWN 修复及采集恢复 | docs/maintenance/judge-context-and-health-fix-report.md，第 10 节 |

“当前规范”表示应该继续维护的入口，不代表已逐字段与最新源码完全同步。尤其 api-contract.md 目前仍偏 Alpha 4 早期摘要，应补进最新 Judge validation/display_mode、健康派生、特殊预告、父帖任务及 reprocess/request 接口。

## 4. 全部项目文档简述

以下各表的文件名均相对于小标题中的目录。阶段报告里的 PID、帖子数量、Prompt 和 PASS/PARTIAL 是**当时快照**，不能替代当前验收。

### 4.1 根目录、应用与数据说明

| 文件 | 大致内容 |
| --- | --- |
| README.md | 项目总索引、现用链路、启停、通知安全边界、回归命令。 |
| apps/backend/README.md | V2 后端启动位置、数据位置、legacy 不参与运行的边界。 |
| apps/web/README.md | 本地 Vite Web 与 /api/v2 代理的开发说明。 |
| apps/collector-extension/README.md | 扩展构建、localhost 通信和过渡采集器说明；仍含 Alpha 1 旧表述，应更新。 |
| data/README.md | Git 只存规范与脱敏样本，不提交真实运行数据的总政策。 |
| data/analysis/README.md | 分析产物默认忽略及公开审查要求。 |
| data/corpus/README.md | 本地历史资料/审核资产用途，退役导入器不再是正式依赖。 |
| runtime/README.md | V2 数据、日志、进程等本地运行目录政策。 |
| backend/data/README.md | V1 数据库和日志的保留说明。 |
| docs/notification_preparation_and_workspace_cleanup.md | 用户提供的通知准备与整理任务书原件；不是实施报告，保留原文。 |

`requirements.txt`（现用后端与 legacy 各一份）是依赖清单，不是业务报告。`VERSION` 是版本来源；`.env.example` 是配置模板；`pytest.ini` 为测试配置。`.env` 只保留本地，不能纳入文档汇编。

### 4.2 docs/notifications（2 份）

| 文件 | 大致内容 |
| --- | --- |
| README.md | 通知安全边界、公共架构、供应商接口与官方依据、配置和开发验证。 |
| testing-guide.md | 用户去哪里扫码/取配置、填哪里、如何单渠道手动测试和记录手机观察；当前唯一用户操作入口。 |

### 4.3 docs/maintenance（盘点时 4 份）

| 文件 | 大致内容 |
| --- | --- |
| `notification-prep-and-cleanup.md` | 9 月 19 日通知准备、工具归档、离线测试与等待手机实测的阶段报告。其 PID 和测试数不是今天的现状。 |
| `reply-context-fix-report.md` | 9 月 20 日父帖自动补全实现、原问题和当时未完成的浏览器验收；未跟踪文件。 |
| `crr-status-20260921.md` | 9 月 21 日修复前全 UNKNOWN 的只读根因报告；未跟踪文件，属于故障现场。 |
| `judge-context-and-health-fix-report.md` | Judge 契约、健康、调度和预告修复；第 10 节记录最新采集恢复验收，前面保留旧现场。 |

本报告新增于本目录，不替代以上报告。建议未来以一个简短状态索引指向最新结论，旧事故现场保留。

### 4.4 docs/v2（含 notifications 子目录）

| 文件 | 大致内容 | 整理定位 |
| --- | --- | --- |
| `local-development.md` | 当前安装、启动停止、环境和验证命令。含未提交启动器说明，整理时保留。 | 当前入口 |
| `architecture.md` | V2 采集→持久任务→分析/翻译→事件→Judge→本地 Web；含父帖获取和边界。 | 当前规范 |
| `api-contract.md` | V2 读取、受控写入和采集兼容接口。尚未完整列出最近新增的状态、预告、重处理接口。 | 当前规范，待同步 |
| `data-model.md` | V2 核心表、长期存储和初始数据边界。 | 当前规范 |
| `product-model.md` | 产品问题、四色/UNKNOWN、24/48/72h、Reset 生命周期与 Judge 边界。 | 当前规范 |
| `migration-from-v1.md` | V1 到 V2 的显式只读迁移、安全要求和语义处理。 | 保留操作参考 |
| `remote-main-divergence-report-2026-09-13.md` | 当时本地与远端 main 分叉的证据及非强推合并方案。 | 历史报告 |
| `v2-foundation-alpha1-report.md` | Alpha 1 基础架构、迁移、版本、目录与初始验收。 | 历史报告 |
| `v2-alpha1-publication-report.md` | Alpha 1 分叉处置、V1 归档、依赖检查及发布记录。 | 历史报告 |
| `v2-local-full-pipeline-report.md` | 9 月 14 日真实推文经过完整产品链的时序与运行验证。 | 历史报告 |
| `corpus-and-wechat-phase-report.md` | 历史语料与早期微信调研的阶段汇总，早于后续结项和通知实现。 | 历史报告 |
| `notifications/wechat-channel-research.md` | 2026-09-17 微信官方与第三方方案调研、条件和取舍；配额价格为当时快照。 | 历史调研 |

### 4.5 docs/v2/corpus（15 份）

| 文件 | 大致内容 | 整理定位 |
| --- | --- | --- |
| `corpus-standard.md` | crr-corpus-v1 统一交换格式、帖子/事件/审核字段与数据库映射。 | 当前规范 |
| `data-policy.md` | 原文、译文、归属、完整度、时间、公开边界和保留原则。 | 当前政策 |
| `gpt-reference-review-procedure.md` | 开发期 GPT 独立整理、冻结输入、逐项结果及人工裁定边界。 | 维护流程 |
| `pipeline-crosscheck-procedure.md` | 用实际产品链做隔离回放；禁止独立 DeepSeek 核查器及答案泄露。 | 维护流程 |
| `corpus-closeout-report.md` | Alpha 4 语料结项、J1—J14、内容限制、回归与已声明限制。 | 阶段最终结论 |
| `corpus-standardization-review-report.md` | 统一审核、人工裁定、回放差异及 Alpha 2/3 修正的累积过程。 | 历史证据 |
| `human-adjudication-followup-20260918.md` | 人工字段级裁定如何执行、回归与重复事件修复。 | 历史证据 |
| `historical-corpus-report.md` | 第一轮历史语料导入、来源、冲突、覆盖和 Judge 集成。 | 历史报告 |
| `historical-corpus-round2-report.md` | 第二轮去重、历史声明、正式/特殊事件、上下文、分析和案例结果。 | 历史报告 |
| `historical-evidence-disposition.md` | 已取得历史声明的逐效果处置、2025 种子和未解决资料。 | 历史清单 |
| `corpus-coverage.md` | 当时实际取得资料的月份/来源覆盖；不是 X 全量完备性证明。 | 版本快照 |
| `source-register.md` | 取得资料的来源登记、可用状态和复用边界。 | 版本快照 |
| `third-party-source-verification.md` | 第三方资料取得与本地核验的区别、原文/作者/时间限制。 | 历史证据 |
| `import-and-verification.md` | 已结束的历史导入流程、幂等、回滚及核验说明；补录工具已退役。 | 历史流程 |
| `tibo-language-patterns.md` | 已审案例中的预告、完成、特殊多效果、否定和延期表达。 | 已审版本参考 |

这些文件存在前后承接而非简单重复：第一轮→第二轮→统一审核→人工跟进→结项。建议索引说明顺序，不把它们粗暴合成一个不断追加的巨型报告。已被清单按路径/哈希引用的文件不要移动或改写。

### 4.6 docs/v1（39 份 Markdown，全部按历史资料理解）

| 文件 | 大致内容 |
| --- | --- |
| `architecture.md` | V1 采集、规则分类和本地后端的最初架构。 |
| `data-model.md` | V1 SQLite 表结构和重复推文的入库语义。 |
| `radar-state.md` | V1 Radar 状态推导说明，不是 V2 Judge 契约。 |
| `operations.md` | 旧启动停止、分类、通知和诊断操作；命令不能当作现行入口。 |
| `troubleshooting-runbook.md` | V1 后端、采集、Mirror、WxPusher、Dashboard 的排障手册。 |
| `observability-architecture.md` | V1 运行日志、诊断存储、健康与查询接口设计。 |
| `observability-contract.md` | V1 事件 envelope、时间、instance、sequence 和错误分类规范。 |
| `public-data-contract.md` | 旧公开 JSON 文件字段及禁止公开的数据边界。 |
| `live-data-mirror.md` | 旧 GitHub 数据分支镜像、同步调度和页面取数说明。 |
| `live-mirror-timing-log.md` | 旧镜像发布和 Dashboard 接收时序日志的关联方法。 |
| `collector-test-results.md` | 2026-08-28 解析器测试和真实 DOM 兼容检查；不是持续采集验收。 |
| `phase-a-progress-report.md` | 第一阶段采集和后端运行进展、未完成项。 |
| `phase-b-classification-report.md` | 早期 46 条推文的规则分类、模型未配置限制。 |
| `phase-b-progress-report.md` | 第二阶段 DeepSeek 分类、Radar 和真实语料验收。 |
| `phase-b5-changed-classifications.md` | 分类校准前后发生类别变化的逐项差异。 |
| `phase-b5-classification-report.md` | B.5 校准后的分类分布、AI 覆盖与 Gold Set 验收。 |
| `phase-b5-progress-report.md` | B.5 总结，关联规则、Prompt、Resolver 和 Radar 修正。 |
| `phase-b5-review-table.md` | 当时高价值推文的人工复核表，包含具体内容证据。 |
| `phase-c-progress-report.md` | 旧 Alert Manager、WxPusher、Windows Toast、去重与健康通知验收。 |
| `phase-d-progress-report.md` | 建立 GitHub 仓库及安全数据镜像的阶段记录。 |
| `phase-e-progress-report.md` | 旧 Pages Dashboard 的功能、部署和线上验收。 |
| `phase-e5-progress-report.md` | 修复页面构建快照不更新及健康语义混淆的历史记录。 |
| `phase-f-progress-report.md` | 中文翻译、本地化、Reset 预计时间和使用建议的阶段结果。 |
| `phase-g-grid-ops-report.md` | 旧 Dashboard 网格布局、设计 token、页面及运维视图改造。 |
| `phase-h-observability-report.md` | 统一可观测性、trace、故障演练和回归记录。 |
| `phase-h1-observability-performance-report.md` | 可观测性性能及日志体积问题、存储改造和验收。 |
| `profile-replies-diagnostic.md` | 旧 Profile/Replies 心跳链路的诊断方法和埋点说明。 |
| `profile-replies-diagnostic-progress-report.md` | 上述诊断阶段进展、观察窗口和根因候选。 |
| `profile-replies-offline-root-cause-report.md` | 旧版本离线事故的实例、时间线和集中补传分析。 |
| `profile-replies-spa-fix-report.md` | 旧采集器单页导航识别问题的修复和真实验证。 |
| `live-mirror-cadence-fix-report.md` | 镜像调度频率问题修复与实际发布验收。 |
| `live-mirror-delivery-diagnostic-report.md` | 镜像到 Dashboard 的接收延迟和事件时间线诊断。 |
| `live-mirror-reliability-fix-report.md` | 镜像重试、可靠性、发布时间语义和运行验收。 |
| `wxpusher-delivery-diagnostic-report.md` | 旧 WxPusher 投递链路、配置状态、Alert 历史与测试诊断。 |
| `project-status-report-2026-09-07.md` | 9 月 7 日后端、镜像、页面和运行风险的综合快照。 |
| `current-development-state-audit-2026-09-13.md` | V1 结束前全项目架构、数据、部署、通知、Git 的审计。 |
| `v1-final-status.md` | V1 最终运行位置、已知失败、测试证据和数据保留边界。 |
| `v1-final-worktree-inventory.md` | V1 收尾工作树、待提交候选、安全检查及快照决策。 |
| `public-data-snapshot/README.md` | 旧公开数据示例快照六类 JSON 的说明；其中 Pages 描述仅适用于历史。 |

### 4.7 非 Markdown 的文档资产

| 文件/目录 | 大致内容与处理边界 |
| --- | --- |
| docs/v1/env.example | V1 配置模板，不能覆盖现行 .env.example。 |
| docs/v1/archive/pages-workflow.yml | 旧 Pages 发布流程存档，非当前生效 workflow，不应搬回 .github。 |
| docs/v1/public-data-snapshot/index.json | 旧公开快照索引/数量。 |
| 同目录 tweets.json | 旧公开推文及分类/翻译快照。 |
| 同目录 radar.json | 旧 Radar、预计时间与建议快照。 |
| 同目录 resets.json | 旧 Reset 记录快照。 |
| 同目录 health.json | 旧健康/心跳快照。 |
| 同目录 meta.json | 旧镜像元数据，不是生产数据库备份。 |
| docs/phase-g-screenshots/overview-en-desktop.png | V1 总览英文桌面截图。 |
| 同目录 overview-zh-desktop.png | V1 总览中文桌面截图。 |
| 同目录 overview-zh-mobile.png | V1 总览中文移动截图。 |
| 同目录 resets-zh-desktop.png | V1 Reset 页面截图。 |
| 同目录 tweets-zh-desktop.png | V1 推文页面截图。 |
| docs/Codex 图像 2026年8月31日 14_37_30.png | 已被忽略规则标记的旧设计示意图，含虚构样例，不是实时数据证据。 |

本轮只盘点图片文件用途，未重新执行图片视觉审查。

### 4.8 本地审核包内的文字材料（不公开提交）

统一前缀：`data/corpus/reviews/unified-review-20260917T094740Z/`。

| 相对该前缀的路径 | 大致内容 |
| --- | --- |
| human-review-queue.md | 初始 GPT/产品实质差异人工队列；不能据此判断今天仍待裁定。 |
| adjudication-20260918/裁决整理说明.md | 收到的人工表单选择及整理方式。 |
| adjudication-20260918/程序回放对照.md | 裁定后 27 条定向样本的程序对照，保留原输出。 |
| adjudication-20260918/user-supplement.txt | 用户补充意见原文，属于裁定资料，不能丢弃或改写。 |
| adjudication-20260918/review-candidate-20260918/remaining-human-adjudication.md | 当时剩余人工字段队列英文版。 |
| 同目录 remaining-human-adjudication-zh.md | 同一阶段的中文人工阅读版，不因内容相近直接删除。 |
| adjudication-20260918/reviewed-corpus-20260918-v1/limitations.md | 已审版本的明确资料限制及字段级裁定边界。 |

审核包还包含 manifest、posts/reset_events、review_cases、review_results、human_decisions 等 JSON/JSONL。它们是逐项事实和追溯记录，不能用 Markdown 汇总替代，也不宜逐份挪出原包。完整原文、模型输入输出、哈希清单留在忽略目录。

## 5. 代码部分简述

### 5.1 apps/backend/app：当前后端

| 模块 | 主要作用 |
| --- | --- |
| main.py | FastAPI 生命周期、健康/Radar/采集/父帖/受控重处理入口和响应组装。 |
| db.py | SQLite schema/迁移、帖子、任务、事件/周期、案例、内容政策、Judge 规范读取与校验；约 100 KB，是核心集中模块。 |
| pipeline.py | 持久任务工作线程、分析翻译、事件处理、Judge 合并/单飞/有界等待。 |
| intelligence.py | 正式分析、翻译、Judge Prompt 和语义结果处理；不是临时核查脚本。 |
| deepseek.py | 已配置 DeepSeek 的 HTTP 调用、返回与失败处理。 |
| reply_context.py | 父帖/祖先关系、内容版本、缓存及上下文可用性。 |
| collector_health.py | 共用采集健康与心跳年龄派生规则。 |
| corpus_standard.py | 标准语料校验、映射、导入导出/内容约束等长期能力。 |
| schemas.py | API 输入数据模型。 |
| config.py | 根目录、本地环境配置、数据库/日志和模型配置。 |
| version.py | 统一版本读取。 |
| logging_runtime.py | 本地结构化日志和保留限制。 |
| __init__.py | Python 包入口标识。 |

notifications 子包：
- `models.py` 消息/结果结构；`config.py` 可选本地配置；`registry.py` 渠道选择。
- `adapters.py` 薄供应商适配；`transport.py` 公共 HTTP 传输；`email.py` 独立 SMTP。
- `service.py` 统一发送/保底流程；`ledger.py` 持久状态去重；`security.py` 脱敏与安全。
- `selftest.py` 离线测试；`__init__.py` 包边界。
- 当前不接生产 Judge 自动通知，不能在整理时顺手启用。

`tests/` 覆盖 API/契约、任务与模型、事件多效果、内容政策、统一语料、父帖、Judge 健康、迁移、日志与通知；`conftest.py` 为共用测试配置。不要将正式回归与 local-archive 中的一次性历史测试混为一谈。

### 5.2 apps/web：当前 Dashboard

| 文件/目录 | 主要作用 |
| --- | --- |
| src/main.ts | 页面组装和更新入口。 |
| src/api.ts、api.test.ts | API 读取、结构解析与测试。 |
| src/radar-ui.ts、radar-ui.test.ts | Radar 展示逻辑、状态/预告文案与测试。 |
| src/config.ts | 前端配置。 |
| src/style.css | 当前样式。 |
| package.json、package-lock.json | 依赖和 test/typecheck/build 命令及锁定版本。 |
| Vite/TypeScript 配置及 index.html | 构建、开发代理和页面壳。 |
| dist、node_modules | 产物与安装依赖，不是手工维护源码。 |

### 5.3 apps/collector-extension：现用扩展

| 文件 | 主要作用 |
| --- | --- |
| src/background.ts | Service Worker、消息转发、搜索调度和 Backend 通信。 |
| src/content.ts | 页面观察、Profile/Replies 识别、扫描与心跳。 |
| src/parser.ts | 页面推文解析。 |
| src/search.ts | 搜索补采逻辑。 |
| src/reply-context.ts | 父帖任务领取、受控详情页/缓存及提交。 |
| src/context-observer.ts | 正常页面结构化响应观察，辅助取得父帖关系/正文。 |
| src/types.ts | 扩展消息/诊断类型。 |
| 对应 *.test.ts | 解析、搜索、父帖与观察器回归。 |
| manifest/构建配置、package 文件 | 扩展权限、入口、依赖和构建。 |
| dist | 实际供浏览器“加载已解压扩展”的产物，清理前必须确认加载路径。 |

### 5.4 scripts：每个入口的用途

| 文件 | 用途/保留建议 |
| --- | --- |
| common-v2.ps1 | 共用项目定位、Python 查找、脱离调用终端的进程启动；有未提交修改。 |
| start-v2-local.ps1 | Backend/Web 启动和归属记录；有未提交修改。 |
| stop-v2-local.ps1 | 只停止本项目进程的安全停止入口。 |
| test-v2-detached-launch.ps1 | 脱离调用终端启动的专项回归；当前未跟踪，先审查归属再提交。 |
| test-notifications.ps1 | Windows 通知测试包装入口。 |
| test_notifications.py | 共用通知 CLI，非 live 操作不发送。 |
| migrate_v1_to_v2.py | 显式 V1→V2 迁移，不是日常启动依赖。 |
| export_corpus_package.py | 通用标准语料导出，长期能力。 |
| replay_corpus_pipeline.py | 调用正式产品链的隔离回放，不能指向生产库。 |
| apply_content_policies.py | 内容可用性政策应用工具，涉及数据变更，不是随便运行的清理脚本。 |
| __init__.py | 脚本包标识。 |
| __pycache__/ | 可重建 Python 缓存。 |

根目录三个 bat 只是相应 PowerShell/CLI 的用户入口，不建议为“文件少”删除它们。

### 5.5 历史代码的三种不同位置

| 位置 | 保存什么 | 是否现用 |
| --- | --- | --- |
| apps/backend/legacy_v1 | 旧后端 app/classifiers/database/intelligence/notifications 与旧测试、依赖、classify_existing.py | 不在 V2 正常启动链；保留迁移/追溯 |
| legacy/v1 | start-radar.bat、stop-backend.bat 和 diagnose/public_export/translate_backfill/sync-github 等脚本 | 历史操作存档，不恢复 Mirror/Pages |
| local-archive/20260919-historical-tools | corpus.py、corpus_round2.py、test_historical_corpus.py、analyse_historical_corpus_round2.py、两轮 import 脚本、run_round2_corpus_judge.py | 一次性退役工具，默认不提交 |

`.github/workflows/ci.yml` 是当前有效 CI：Backend 测试，Web/Collector 测试、类型检查和构建。docs/v1/archive 下的 Pages workflow 只是档案，两者不可互换。

## 6. 运行资产和临时目录怎么理解

| 区域 | 当前规模 | 说明 |
| --- | ---: | --- |
| runtime/data | 20.76 MiB | 当前本地数据库，SQLite 主文件与 WAL/SHM 需一致性处理，不能边跑边散删。 |
| runtime/logs | 8.24 MiB | 现用结构化业务日志，已有保留策略。 |
| runtime/launcher | 8.41 MiB | 启动/运行输出证据，另于业务日志。 |
| runtime/backups | 1.04 MiB | 备份目录；其他专项证据目录也有备份，不能只凭此目录判断是否有备份。 |
| runtime/review | 30.10 MiB | 16 个历史回放子目录，v5 全量、v6/v7/v8 定向、人工跟进、结项等，不是 16 份等价重复。 |
| runtime/reply-context-fix | 5.77 MiB | 父帖修复证据。 |
| runtime/judge-health-fix-20260921 | 3.83 MiB | before.db、before.json、acceptance.json、recovery-acceptance.json 等，故障/恢复前后证据。 |
| runtime/notification-tests | 0.01 MiB | 通知准备测试输出，不等于真实送达。 |
| runtime/pids | <0.01 MiB | 服务归属信息，进程运行时不要清空。 |
| data/corpus | 10.39 MiB | 历史导入和审核包；manifest 引用与人工输入需保持完整。 |
| _tmp | 13.58 MiB | 两份干净源码副本、16 个 public-data-sync-* 目录、若干临时脚本和 SQLite。 |

`_tmp/judge-health-clean-20260921` 和 `_tmp/reply-clean-...` 各约 3.5 MiB。它们是正式源码验证副本，不是主源码；此前 Judge 副本清理曾被工具策略拒绝，本报告不重试删除。旧 public-data-sync 目录可能包含 worktree 元数据，正式清理前应结合 `git worktree list` 和进程占用确认，不能单看名字批量删。

## 7. 整理时最值得处理的混淆

| 现状 | 容易误解成 | 建议 |
| --- | --- | --- |
| docs/v2/notifications 与 docs/notifications 并存 | 两套当前通知文档 | 前者标历史调研，后者唯一当前指南；需要移动时先查链接。 |
| apps/backend 与根 backend 并存 | 两套活跃后端 | 根 backend 标明“环境与 V1 数据保留”；如迁移环境，先改启动器并验收。 |
| apps/web 与 dashboard 并存 | 两套现用页面 | 旧 dashboard 构建/依赖单独评估，无需改现用 apps/web。 |
| apps/collector-extension 与 extension 并存 | 两份都可删/互换 | 先核实浏览器加载的 dist，不能凭旧目录名下结论。 |
| maintenance 中故障报告与修复报告共存 | 系统仍停留在故障状态 | 索引链接“故障→修复→最新恢复节”，旧报告不覆写。 |
| 语料多轮报告内容相近 | 可以保留最后一份、删前面 | 保留审核证据链，最新结项作为阅读入口。 |
| Git 忽略的 runtime/data、data/corpus | 临时垃圾 | 忽略仅表示不提交，完全不表示可删。 |
| 旧 V1 operations 和快照 README 仍写 Pages/Mirror | 可以照做恢复旧链路 | 增加历史提示，不以旧命令操作当前系统。 |

### 建议的整理顺序（未执行）

1. **先定入口**：保留 README 为总索引；补一个简短“当前/历史”目录索引即可，不再复制架构和配置全文。
2. **同步现行规范**：更新 API 契约及 Collector README 的过时表述；报告中的历史数值保持不动。
3. **给历史材料加导航**：V1 继续原位；V2 报告可先通过索引归类，只有确认无不可变引用后才考虑移动到 docs/v2/archive。
4. **保护未提交成果**：先审查启动器、local-development.md、未跟踪报告/任务原件，不能用清理工作树代替归档。
5. **检查可重建项**：先确认旧 dashboard/extension 无运行依赖，再考虑旧 node_modules/dist；现用扩展 dist 暂保留。
6. **单独做 V1 数据留存决定**：核对备份可读性、证据价值、保留期限，再决定外部归档或清理旧日志；不直接删 radar.db。
7. **最后清理临时副本/缓存**：核实 worktree、进程和唯一副本后操作，记录释放字节数。移目录不是释放磁盘空间。

**最小推荐方案**：先不搬任何语料/历史证据，补索引和历史标识；把真正的磁盘释放工作限定在已经验证可重建且不在使用的旧产物，以及另行批准的 V1 日志。

## 8. 本轮保护与交付

本轮未移动、删除、压缩任何现有文件；未修改业务源码、Prompt、配置、数据库；未停启服务、触发模型或发送通知。

盘点时已有未提交内容继续保留：
- 已修改：docs/v2/local-development.md、scripts/common-v2.ps1、scripts/start-v2-local.ps1。
- 未跟踪：docs/maintenance/crr-status-20260921.md、docs/maintenance/reply-context-fix-report.md、docs/notification_preparation_and_workspace_cleanup.md、scripts/test-v2-detached-launch.ps1。

本报告只为整理决策提供地图，未证明任意整个目录可以安全删除，也未对所有历史链接执行完整有效性检查。后续真正搬迁时应逐项验证链接、manifest 引用、运行占用和干净源码依赖。
