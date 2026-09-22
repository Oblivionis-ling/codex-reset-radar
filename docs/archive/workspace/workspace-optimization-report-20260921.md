# 工作区优化与文档治理结项

日期：2026-09-21。总体：**PARTIAL**（主要整理与回归已完成；无法核实的旧扩展加载路径、固定数据引用和旧临时副本明确保留，不为目录整齐冒险删除）。

项目：`D:\work\20260828-CodexResetRadar`。分支：`chore/workspace-optimization-20260921`。
本轮没有更改 Radar 等级规则、Prompt、模型、父帖逻辑、采集频率、事件/周期、人工裁定或通知策略。

## 1. 日常入口和文档结果

- 根 [README](../../../README.md) 只保留简介、三个 BAT 与文档入口。
- [docs/README](../../README.md) 集中 12 份当前正文、固定证据和未结案维护。
- [历史导航](../README.md) 给出原路径到归档位置的映射及阅读顺序。
- [通知测试](../../notifications/testing-guide.md) 仍是用户唯一操作指南，未宣称手机验收完成。
- 应用 README 缩为职责、目录和命令入口；Collector 的 Alpha 1 表述已去除。
- 当前 API 文档补齐 validation、两类 data_health、display_mode、last_known_result、special_announcements、父帖任务、reprocess/judge request 的实际接口。
- 数据模型、产品模型补充当前存储/校验和预告展示边界，架构指向正确的 legacy 路径。
- 原有 corpus 四份标准/流程和已审表达案例不改语义；数据/运行目录 README 已各司用途，没有为凑数量再合并。
- 27 个普通文件按表归位（含本轮任务原件及五张截图）；旧设计 PNG 原样移入被忽略的 local-archive/design/v1。
- 语料结项报告 **PINNED_KEEP**：验收 JSON 固定路径与 SHA256；当前 SHA256 仍为
  `c692506d763bb9757983e3a3b1e02b8de6aafdbc460feddcd84d26204f560fc4`。
- Judge 修复报告仍留 maintenance，页面视觉与远端发布未结束，未伪装结案。

链接检查：当前本地 Markdown 链接坏链 **0**。对 archive 和 V1 也执行扫描，没有将整个历史目录忽略。
修正了五个截图链接和两个 Gold Set 链接，仅改变链接目标，不改变历史结论。
仍有 **4** 个旧引用在 `docs/v1/profile-replies-diagnostic-progress-report.md`：
`../extension/src/content.ts`、`../extension/src/background.ts`、
`../backend/app/main.py`、`../backend/app/models/__init__.py`。
它们指向当时源码，未盲目改指今天不同语义的文件；从历史导航/Git 历史追溯。
详细结果在本地 `link-check.json`。

## 2. 代码与环境整理

### 已证实的重复

| 旧位置/调用者 | 等价依据 | 处理及测试 |
| --- | --- | --- |
| stop-v2-local.ps1、test-v2-detached-launch.ps1 的根目录推断 | 都取 scripts 的父目录，和 common-v2 完全相同 | 改用 common-v2.ps1 的 CrrRepositoryRoot；真实安全停启和 WMI 脱离进程回归通过 |
| start/test-notifications 的 Python 查找 | 原本已共享 common-v2；无需再建 helper | 保留共享入口，删除旧环境回退，缺新环境明确报错 |

Judge raw 规范化、collector_health、通知脱敏/传输已是正式单一入口，未复制或重写。
Python 工具在导入 app 前的路径 bootstrap 与 app.config 的运行配置不是无条件等价，保留。
解析来源/未知时间语义不同，未合并。未拆分 db.py、事务或 SQL，也未删除相似但必要的回归。

### Legacy

`apps/backend/legacy_v1/` → `legacy/v1/backend/`：37 个被跟踪文件，100% 内容保留。
已搜索正式 app、tests、scripts、CI、pytest 配置，无现用 legacy_v1 导入依赖。
现用代码集中 apps；历史 Mirror/启动脚本保持 legacy/v1；一次性语料工具留 local-archive。

### Python 环境

旧 `backend/.venv` 实际仍被使用，所以先创建 **apps/backend/.venv**，未移动虚拟环境文件。
安装使用原环境精确版本快照，无主动升级；pip check 通过。版本快照保存在本地。
新环境先完成 89 项 Backend 测试及 9 渠道 OFFLINE_PASS，再通过原安全停启入口切换。
核实新的 venv 启动进程可执行路径为：
`D:\work\20260828-CodexResetRadar\apps\backend\.venv\Scripts\python.exe`。
旧环境无进程引用且正式入口不再回退后，按文件白名单删除；失败时会保留旧环境，本次切换成功。
原先未提交的 WMI 脱离启动改动完整保留，经其专项测试后作为独立脚本提交保存，不归功为本轮新业务能力。

## 3. 旧目录与保留原因

| 路径 | 结果 |
| --- | --- |
| backend/.venv | 已删除旧可重建环境；依赖快照可用于重建 |
| backend/data | 原位保留。data/analysis/v1-reset-migration-candidates.json 保存该库的绝对来源路径，本轮不改该迁移证据；数据库未删未裁表 |
| dashboard/node_modules、dist | 无进程/正式脚本使用，Git 历史有依赖锁与源码；已删除 |
| extension/node_modules | 旧依赖已删除；当前 apps/collector-extension 依赖不动 |
| extension/dist | 保留：未可靠确认 Edge 是否仍加载该具体旧目录。没有把新磁盘 manifest 当作加载证明 |
| _tmp/judge-health-clean-20260921 | 既有 BLOCKED_BY_POLICY，未再次尝试或绕过 |
| _tmp/reply-clean-* | 非注册 worktree，但未证明所有本地内容可从唯一已保存状态重建，保留 |
| 16 个 _tmp/public-data-sync-* | worktree 清单仅有主工作树；逐目录无 .git 指针。它们是未注册导出残留，未证明每份历史快照可重建，因此保留，不当作16个相同垃圾 |
| _tmp 既有其他脚本/数据库 | 未证明不是唯一资料，保留；与本轮临时验证副本分开 |
| local-archive/20260919-historical-tools | 原位保留，不提交，不被正式 import |
| runtime/data、pids、backups、review 及专项验收目录 | 保持原位，未套用普通日志 TTL |
| data/corpus、analysis | 保持原位；固定资产哈希检查无变化 |

没有手工修改 .git/worktrees 元数据，没有 git clean/reset/force push。
空目录仅在确认内部为空后处理；仍有有效资产的 backend/extension/_tmp 不强制消失。

## 4. 空间结果（逻辑字节，不是 NTFS 实占用）

| 类别 | 实际删除字节 | 说明 |
| --- | ---: | --- |
| 旧 dashboard/extension 依赖与旧 dashboard 构建 | 118,712,603 | 约 113.21 MiB |
| 旧 Python 环境 | 65,521,053 | 约 62.49 MiB；新位置也安装了环境，不等于净节省同样大小 |
| 根 pytest 与 scripts Python 缓存 | 138,283 | 可重建；后续测试可能生成新缓存 |
| 11 份 V1 过期普通 Backend 事件日志 | 1,585,611,918 | 约 1.48 GiB；超过5天，检查首尾日期、独占读取和引用后删除 |
| **上述旧资产删除合计** | **1,769,983,857** | **约 1.65 GiB 的逻辑文件长度** |

日志没有全量复制到另一目录冒充释放；处置表保留每份大小、SHA256、首尾时间与事件类型，
H.1 性能事故报告、V1 最终报告及数据库继续保留。删除日志不是移入回收站；本轮没有全量恢复副本，
如以后需要原始日志只能依赖此前已有备份。旧依赖/构建可按 Git 历史和版本快照重装重建。

普通报告、截图和设计 PNG 的 MOVE/ARCHIVE_LOCAL **释放 0 字节**。
新增 Python 环境、测试缓存和本轮证据会抵消部分删除量；未测 NTFS 压缩/分配大小，不宣称净磁盘空闲增加恰好 1.65 GiB。
本轮干净源码验证副本的创建与清理单独记账，不混入旧资产回收额。

旧 V1 runtime 文本日志和通知/投递日志未一并删除：本轮白名单只覆盖已核验的 Backend 事件日志；
投递测试与诊断材料未完成逐项唯一证据判断。现用 launcher 未截断，现有启动轮转保留；没有新增第二套日志框架。

## 5. 测试与运行验收

| 检查 | 结果 |
| --- | --- |
| 新环境 Backend 正式回归 | 89 passed |
| Web | 7 passed；typecheck/build 通过 |
| Collector | 18 passed；typecheck/build 通过 |
| 通知离线 | 9 种渠道变体 OFFLINE_PASS；真实发送 0 |
| 脱离终端启动专项 | WMI 所有的探针在调用者结束后仍存活；只结束测试进程 |
| 实际安全停启 | 只停止本项目已验证 PID，新路径 Backend/Web 启动成功 |
| 干净正式源码 Backend | 89 passed；复用已验证新 Python 环境，不依赖旧 backend/.venv |
| 干净源码 Web/Collector | 各自 npm ci --ignore-scripts 后测试、类型检查、构建通过；不使用旧根 node_modules |
| 干净源码通知 | 9 渠道 OFFLINE_PASS，内存模拟传输 |
| 数据库只读检查 | quick_check=ok，外键错误0；14正式事件、13周期 |
| 固定证据 | protected-hashes 校验无差异；结项报告与固定验收 SHA256 一致 |
| 敏感文件/大文件 | 拟提交清单无 .env、数据库、日志、完整审核包；密钥模式扫描无发现 |

干净源码来自显式暂存文件的 checkout-index，不是复制整个工作区。没有复制 .env；
CI/测试走隔离数据库与 Mock，通知 selftest 有网络阻断。依赖安装访问包仓库，不属于真实通知或模型请求。

维护重启后 Profile/Replies 在 23:38、23:39、23:43（北京时间）有正常间隔的新心跳，
同实例 sequence 持续增加，随后仍有实际扫描入库；Search 独立心跳/采集恢复。
健康 API 为 HEALTHY；Backend 与 Web 代理相同 Judge/等级。详细采样见本地 runtime-after.json。
服务继续运行，无浏览器关闭或扩展重载。

本轮主动模型请求 **0**，未调用 reprocess/judge request、未跑全库或14窗口。
维护启动及健康恢复自然合并产生 **1 次成功 Judge（238）**，无重试；这是运行调度，不冒称整理离线测试。
原有小时调度继续正常，本报告不宣称整个日期模型请求为0。
运行版本仍 **2.0.0-alpha.4**，业务指纹 **c9b1fd210a8ee0e1**，Prompt 未改。
微信真实发送 **0**；邮件真实发送 **0**。

## 6. 提交与证据

本地分组提交：
- `9d30b9d`：只集中 V1 Backend 历史源码。
- `b249ee7`：保存既有脱离启动成果、共用根定位、新 Python 唯一路径。
- 文档归档、规范同步及本报告：见本报告所在提交，避免自引用提交哈希。

未推送、未合并 main、未创建或移动标签；没有把尚未发布的 Judge/通知能力标为正式发布。
用户原件原样归档，原有启动器和运行说明修改已保护并纳入对应提交，不以丢弃修改换干净工作树。

唯一结项报告为本文件。详细本地记录：
`D:\work\20260828-CodexResetRadar\runtime\workspace-cleanup-20260921\`

- path-actions.jsonl：逐文件/目录动作、依据、大小、哈希和结果。
- preexisting.patch、status-before.txt：此前成果恢复线索。
- protected-hashes.json、protected-verification.json：审核资产不变证明。
- environment-before.txt：旧环境版本快照。
- link-rewrites.json、link-check.json：普通链接调整和历史例外。
- runtime-after.json：维护后的只读运行回执。

## 7. 剩余边界

1. Edge 对旧 extension/dist 的实际加载目录尚未确认，故不删除；不要求用户为其他已完成整理停工。
2. V1 数据来源路径引用与旧临时导出的唯一性尚未解除，明确保留，不靠批量移动制造整齐。
3. 先前策略拒绝的 Judge 临时副本未重试。
4. 历史文档四个源码旧链接保留为历史例外；当前导航与规范无坏链。
5. 本轮不是页面视觉验收、通知手机验收或发布验收，原维护事项未因此结案。

本轮到此停止，不继续开发语料、通知、Dashboard 或服务器能力。
