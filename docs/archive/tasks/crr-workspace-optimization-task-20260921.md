# Codex Reset Radar — 工作区优化与文档治理任务书

## 0. 任务依据与目标

依据：`project-directory-and-document-inventory-20260921.md`。它是目录、文件用途和部分引用关系的盘点，不是完整代码审计；以下目录大小、文件数量只作为基线，执行时重新核实。

本轮完成三件事：

1. **当前说明与历史报告分开**：保留少量权威文档，将普通历史报告集中归档，保护不可变审核证据。
2. **清退无用副本和旧运行残留**：按明确条件删除旧依赖、可重建临时文件和过期普通日志，不误删环境、数据库、审核包或正在使用的扩展。
3. **精简实际重复代码**：先核查调用关系，再合并同语义实现；不凭目录名或文件大小推倒架构。

整理后，日常使用者只需要知道：根目录 README、三个应用、当前运行指南、通知测试指南、当前数据位置。历史资料依然可找，但不再与当前规范混读。

本轮不是产品开发。不得改变 Radar 等级、Judge/分析/翻译 Prompt、人工裁定、父帖逻辑、事件与周期语义、采集频率或通知策略。通知准备和父帖修复已有成果必须保留。

---

## 1. 总体决定：不再重排现用应用

以下位置固定保留：

```text
README.md
VERSION
.env.example
.env                              # 本地私有
start-v2-local.bat
stop-v2-local.bat
test-notifications.bat
apps/backend/app/
apps/backend/tests/
apps/web/
apps/collector-extension/
scripts/                          # 正式脚本入口
.github/workflows/ci.yml
runtime/data/                     # 当前数据库
runtime/pids/                     # 当前进程归属
runtime/logs/
runtime/launcher/
data/corpus/
data/analysis/
```

不改 `apps/` 顶层布局，不修改用户已有的正常启动、停止与通知测试入口。根目录的三个 BAT 很小，但有实际用户价值，不为“文件少”而删除。

本轮不把运行数据移出 `runtime/data`，不搬动整套语料包，不迁移项目根目录，不修改仓库名称。

---

## 2. 安全准备：保护未提交成果与正在运行的服务

### 2.1 重新盘点

记录当前分支、HEAD、工作树、被跟踪/未跟踪/忽略状态、实际 Backend/Web 进程、Python 路径、扩展加载路径和磁盘大小。

特别保护清单已列出的变化，并检查是否又增加了新变化：

```text
docs/v2/local-development.md
scripts/common-v2.ps1
scripts/start-v2-local.ps1
scripts/test-v2-detached-launch.ps1

docs/maintenance/crr-status-20260921.md
docs/maintenance/reply-context-fix-report.md
docs/notification_preparation_and_workspace_cleanup.md
```

微信、启动器或其他 Codex 任务仍在修改共享文件时，先协调这些文件串行修改。其他不冲突的文档工作继续，不要整体阻塞，也不要覆盖对方修改。

### 2.2 建立可恢复记录

创建本地忽略目录：

```text
runtime/workspace-cleanup-20260921/
```

仅保存本轮需要的文件处置清单、有限检查结果和恢复说明，不复制一整套项目、node_modules 或现用数据库到这里制造新膨胀。涉及数据库相关操作，复用现有一致性备份机制。

维护一个机器可读处置表 `path-actions.jsonl`，每项包含：

```text
old_path / new_path
tracked_state
action
reason
dependency_check
pinned_evidence_check
size_before
verification
result
```

动作限定：

```text
KEEP
MOVE
MERGE_DOC
ARCHIVE_LOCAL
DELETE_REBUILDABLE
DELETE_EXPIRED_LOG
PINNED_KEEP
BLOCKED
```

不得对用途不明的文件使用删除动作。

### 2.3 禁止事项

禁止 `git reset --hard`、无审查的 `git clean`、整目录 `Remove-Item`、强推、覆盖旧标签，以及为获得 clean 状态而丢弃修改。

禁止遍历 junction/symlink 后误处理项目外路径。禁止手工删除 `.git` 内对象或 worktree 元数据。

禁止清除正在使用的 PID 文件、拆散运行中的 SQLite/WAL/SHM、移走进程正在使用的 Python 环境。

工具策略拒绝删除时记录 `BLOCKED_BY_POLICY` 并跳过，不换编码命令或其他工具绕过限制。

---

## 3. 目标文档结构：当前约 12 份正文，历史一个导航入口

保留现有 `docs/v2` 作为当前规范目录，**不再新增一份 docs/current 复制同样的正文**。

```text
docs/
├── README.md                      # 唯一文档导航：当前、历史、固定证据
├── v2/
│   ├── local-development.md
│   ├── architecture.md
│   ├── product-model.md
│   ├── data-model.md
│   ├── api-contract.md
│   └── corpus/
│       ├── corpus-standard.md
│       ├── data-policy.md
│       ├── gpt-reference-review-procedure.md
│       ├── pipeline-crosscheck-procedure.md
│       └── tibo-language-patterns.md  # 已审版本参考，不混作实时规律
├── notifications/
│   ├── README.md
│   └── testing-guide.md
├── maintenance/                   # 仅未结束维护的工作报告
├── archive/
│   ├── README.md                  # 历史导航和旧路径映射
│   ├── v2-foundation/
│   ├── corpus/
│   ├── notifications/
│   ├── incidents/
│   ├── tasks/
│   └── workspace/
└── v1/                            # 已集中好的 V1 档案，整体维持原位
```

不必创建空目录。少量被不可变清单绑定的旧报告可能必须留在原位置，索引将其归类为“固定历史证据”，不复制正文、不让它成为当前操作入口。

不要把几十篇报告合成一个数万行、不断追加的“总报告”。**集中归档是集中位置和索引，不是混合所有历史内容。**

---

## 4. 当前文档的维护分工与同步要求

| 文件 | 本轮处理 |
|---|---|
| 根 README.md | 保留产品简介、三个 BAT 入口、指向 docs/README 的链接；删除重复的大段架构/操作正文，唯一信息先迁入对应当前文档。 |
| docs/README.md | 列当前 12 份文档、各自用途、历史入口、固定证据例外；不再复制配置和架构全文。 |
| docs/v2/local-development.md | 保留未提交启动器成果，写清实际 Python 环境、三应用命令、路径、手动浏览器步骤及准确日志位置。 |
| docs/v2/architecture.md | 只写当前实际业务链及边界，去除已失效设计，不混入阶段 PID、记录数和运行快照。 |
| docs/v2/product-model.md | 集中维护四色、白色 UNKNOWN、紫色特殊事件、24/48/72h 和完整 Reset 周期含义。 |
| docs/v2/data-model.md | 与当前 schema、迁移、父帖关系、语义版本、候选/正式事件、内容政策、Judge 数据结构一致。 |
| docs/v2/api-contract.md | 必须补齐真实代码中的 validation、current_data_health、judgement_data_health、display_mode、last_known_result、special_announcements、父帖任务和受控 reprocess/judge request。准确接口路径从源码/当前 OpenAPI读取，不凭旧报告猜。 |
| docs/v2/corpus 下 4 份规范/流程 | 保留；格式、政策、GPT 整理、程序回放分别负责自己的内容，重复内容改为链接，不合并成一个巨型文件。 |
| tibo-language-patterns.md | 保留为已审版本参考，标明版本、样本限制和非固定升色规则；不可为了文档去重改变已有审核结论。 |
| docs/notifications 两份文档 | 保持当前唯一通知开发说明及用户操作指南；渠道是否离线测试、待配置、待手机测试据实说明。 |

应用 README 保留，改成很短的职责、目录、命令入口与当前文档链接。尤其更新 Collector README 的 Alpha 1 过时描述，但不得把“磁盘构建存在”写成“浏览器已经加载该版本”。

`data/README.md` 集中维护不提交真实数据的政策；`data/corpus/README.md`、`data/analysis/README.md`、`runtime/README.md` 只写各自目录用途与特别保护项，避免四份重复全文。

当前文档以源码及可验证结果为准。历史报告中的时间、PID、PASS/PARTIAL 和当时数量不改成今天的值。

---

## 5. 普通历史文档的准确搬迁表

**先执行第 6 节的固定证据检查，确认没有不可变引用，才应用本表。** tracked 文件使用 `git mv`；未跟踪文件普通移动，保留原文并审查是否适合提交。

### 5.1 早期 V2 与跨版本说明

| 原路径 | 目标路径 |
|---|---|
| docs/v2/remote-main-divergence-report-2026-09-13.md | docs/archive/v2-foundation/remote-main-divergence-report-2026-09-13.md |
| docs/v2/v2-foundation-alpha1-report.md | docs/archive/v2-foundation/v2-foundation-alpha1-report.md |
| docs/v2/v2-alpha1-publication-report.md | docs/archive/v2-foundation/v2-alpha1-publication-report.md |
| docs/v2/v2-local-full-pipeline-report.md | docs/archive/v2-foundation/v2-local-full-pipeline-report.md |
| docs/v2/corpus-and-wechat-phase-report.md | docs/archive/corpus/corpus-and-wechat-phase-report.md |
| docs/v2/migration-from-v1.md | docs/v1/v1-to-v2-migration.md |

迁移操作文档与迁移脚本仍保留，只退出日常入口；该操作可能仍用于恢复，不因为当前不常运行就删除脚本。

### 5.2 语料历史文件

将 `docs/v2/corpus/` 下以下文件搬至 `docs/archive/corpus/`，保留原文件名：

```text
corpus-closeout-report.md
corpus-standardization-review-report.md
human-adjudication-followup-20260918.md
historical-corpus-report.md
historical-corpus-round2-report.md
historical-evidence-disposition.md
corpus-coverage.md
source-register.md
third-party-source-verification.md
import-and-verification.md
```

归档导航按“第一轮 → 第二轮 → 标准化 → 人工裁定 → 结项”解释阅读顺序。

这些不是简单重复，不删除独有的事故、裁定和处理结果。第三方来源登记不再是日常 Judge 或自有采集必须维护的入口。

### 5.3 通知、事故、任务和盘点

| 原路径 | 目标路径／处理 |
|---|---|
| docs/v2/notifications/wechat-channel-research.md | docs/archive/notifications/wechat-channel-research.md；移动成功后移除空的旧 notifications 目录。 |
| docs/maintenance/notification-prep-and-cleanup.md | docs/archive/notifications/notification-prep-and-cleanup.md；测试操作仍查当前 testing-guide。 |
| docs/maintenance/reply-context-fix-report.md | docs/archive/incidents/reply-context-fix-report.md |
| docs/maintenance/crr-status-20260921.md | docs/archive/incidents/crr-status-20260921.md |
| docs/maintenance/judge-context-and-health-fix-report.md | 页面或发布仍未结束时暂留 maintenance；结案后再移 docs/archive/incidents/。不得为了清空目录假装结案。 |
| docs/notification_preparation_and_workspace_cleanup.md | docs/archive/tasks/notification_preparation_and_workspace_cleanup.md；任务原件不是实施说明。 |
| docs/maintenance/project-directory-and-document-inventory-20260921.md | docs/archive/workspace/project-directory-and-document-inventory-20260921.md |

本次清理结项报告最终也放入 `docs/archive/workspace/`，只维护一份，不在各个子目录重复生成报告。

### 5.4 视觉资产

- `docs/phase-g-screenshots/` → `docs/v1/design/phase-g-screenshots/`，完整保留五张截图。
- `docs/Codex 图像 2026年8月31日 14_37_30.png` → `local-archive/design/v1/`，维持忽略状态。它是设计参考，不是业务数据；不因内含虚构样例就删除设计资产。
- 如任一图片被不可变清单引用，保留原位并在索引中定位。

V1 的 39 份 Markdown、公开示例快照、旧 env.example 和 Pages workflow 存档已集中好，默认不再大搬迁。旧 workflow 绝不能移回 `.github/workflows`。

---

## 6. 固定证据与链接规则：既要整齐，也不能破坏审核包

搬任何报告、图片、验收 JSON、备份或回放目录之前，检查：

```text
manifest 与 SHA 清单
acceptance／comparison／human decision 文件
相对路径和绝对路径引用
当前 scripts、CI、AGENTS 与测试中的文件读取
动态目录发现与路径配置
```

处理分三类：

1. **固定路径、固定哈希或审核包组成部分：** 不移动、不改字节、不伪造重定向替身。标记 `PINNED_KEEP`，由 docs/README 与 archive/README 提供唯一导航。必要时记录为什么仍在旧位置。
2. **普通报告和相对链接：** 可以搬迁，必要时只修正超链接地址，不改历史结论；记录移动前后哈希及修改性质。
3. **报告中作为历史事实保存的旧路径或旧命令：** 不做全局替换。通过归档索引说明它是历史路径，不是当前运行指令。

不能为了搬目录重写已签收 manifest，也不能复制“当前版、归档版、兼容版”三套正文。

普通当前文档的旧链接直接更新。确有外部固定入口时最多保留短链接说明，且不得覆盖固定证据文件；不要默认给每个移动文件生成占位页。

验收中分别统计：当前文档坏链接必须为零；历史快照无法重写的旧引用单列说明，不能靠忽略整个 archive 假装全部链接通过。

---

## 7. 旧代码集中：只移动未参与运行的 Legacy

| 原路径 | 决定 |
|---|---|
| apps/backend/legacy_v1/ | 检查无 V2 运行、迁移、测试或 CI 的隐式依赖后，移动至 `legacy/v1/backend/`。保持内部结构，不拆散历史代码。 |
| legacy/v1/ 既有旧启动器、Mirror、诊断脚本 | 原位保留，不恢复成根目录可执行入口。 |
| local-archive/20260919-historical-tools/ | 原位本地保留，不公开提交，不再由正式代码 import。约 0.09 MiB，不为“空间”折腾。 |

如正式 V2 确实引用了 legacy 中一个必要 helper，先判断它是否属于长期能力；将必要实现迁入现有合适模块，保留兼容并测试。不要为搬目录复制整套旧数据库或模型实现。

历史内部说明指向原启动环境并不等于当前依赖。检查真实运行调用、pytest 收集和脚本导入，区分两者。

最终应形成：现用代码只在 `apps`，历史代码集中在 `legacy/v1`，一次性工具仅在本地归档。

---

## 8. 旧根目录 backend：先解除环境依赖，最后才移除

清单明确 `backend/.venv` 仍是启动器有效回退，不能先删 `backend/`。

执行顺序：

1. 确认当前 Backend 的真实解释器、`common-v2.ps1` 的查找逻辑、各脚本与文档引用。
2. 已有可用 `apps/backend/.venv` 就复用；没有则依据现有正式依赖在新路径创建并安装，不移动旧虚拟环境文件，不主动升级依赖。
3. 在新环境运行正式 Backend 测试、启动、通知离线自测及脚本检查。
4. 使用安全停启入口切换本项目 Backend，核验实际解释器、代码身份、API 和三路采集；失败立即使用旧环境恢复。
5. 确认所有正式入口均已使用新环境后，删除旧路径的自动回退；安装缺失时给明确说明，不能静默启动错误环境。
6. 旧 `.venv` 在没有进程使用、正式启动不再依赖、验证通过后才列为 `DELETE_REBUILDABLE`。

V1 数据库另行处理，不能被第 6 步带删：

```text
backend/data/ → local-archive/v1-runtime/data/
```

仅当确认 V1 没有写入进程、无固定证据路径约束、数据库及剩余文件可读，并完成必要当前引用更新后才移动。保留数据库完整副本，不执行业务表或审计表裁剪。

原 `backend/data/README.md` 随目录保留并补充本地归档用途。迁移脚本的当前说明改用显式源路径或新的归档路径，不执行一次真实迁移来“测试路径”。

数据被固定证据路径引用时，保留原位并说明；旧目录仍有唯一有效资产时不要强行删除父目录。**不能以根目录必须消失为由破坏证据。**

---

## 9. 明确可以删除的候选及前置条件

| 候选 | 允许删除的前提 |
|---|---|
| 根目录 `dashboard/node_modules/` | 无活动进程、脚本或正式测试使用，依赖可以从历史版本重建。 |
| 根目录 `dashboard/dist/` | 无当前使用；不是唯一的旧视觉素材，必要设计资产已保留，或产物可重建。 |
| 根目录 `extension/node_modules/` | 无活动构建或测试使用，已核实属于旧扩展。 |
| 根目录 `extension/dist/` | **确认 Edge 实际未加载这个目录**；只看到新版 manifest 文件不算确认。不能确认就先保留这部分。 |
| 根目录 `.pytest_cache/`、正式 scripts 下 `__pycache__/` 等生成缓存 | 不属于测试 fixture、审核包或环境内容；按白名单清理，不全盘递归搜索删除。 |
| `_tmp/judge-health-clean-20260921`、`_tmp/reply-clean-*` | 确认是可由已保存提交或记录重建的源码副本，无唯一代码、未保存修改、数据库证据或运行进程。 |
| `_tmp` 内其他临时脚本／数据库 | 逐项核实非唯一资料、无在用和固定证据引用；不能凭扩展名直接删。 |
| `_tmp/public-data-sync-*` | 先按第 10 节处理 Git worktree，再决定移除。 |

当前 `apps/*/node_modules`、当前 Web `dist` 和正在加载的 Collector `dist` 本轮默认保留。不为释放少量空间重新要求用户安装依赖、重载扩展。

旧 dashboard/extension 目录检查完成后，只有真的为空才删除父目录。唯一且无法重建的设计资产移到本地设计归档，其余不要整目录转移后声称释放了空间。

---

## 10. `_tmp` 与 worktree 使用正规清理路径

先执行只读 `git worktree list --porcelain`，确认每个候选是否为注册工作树、被锁定、存在未提交文件、独有提交或其他引用。

注册工作树先保存应保留的成果，满足清理条件后使用正常 `git worktree remove`。不得 `--force` 丢弃修改，不手工删除 `.git` 指针或直接删根仓库的 worktrees 元数据。

未注册目录也要确认其 `.git` 指针、来源、唯一性和占用后再普通删除。不能假设全部 16 个 public-data-sync 目录都属于相同类型。

已有工具策略拒绝删除的目录不绕过限制，列入保留项，不因此阻塞文档整理、公共代码去重和其他正常清理。

---

## 11. V1 大日志：精确保留证据，过期普通日志可以清理

清单中 `backend/data` 约 3007.18 MiB，其中 `radar.db` 约 1232.18 MiB。本轮明确：**数据库不删；普通旧日志不默认永久保留。**

优先检查的大文件：

```text
observability/events/backend-events-legacy-2026-09-08.jsonl
observability/events/backend-2026-09-08.jsonl
observability/events/backend-2026-09-09.jsonl
同日带后缀的 legacy 事件日志
```

### 可删除的条件必须同时满足

- 是普通 V1 运行日志，不是原文语料、人工裁定、唯一事故证据或数据库。
- V1 已不再写入，没有活动进程持有该文件。
- 超过用户已确定的五天普通日志保留期；结合日志日期和有限尾部检查，不只凭最近复制时间。
- 没有不可变清单绑定，也不属于尚未结案问题必须保留的证据。
- 已保留必要的脱敏摘要、代表性异常片段或已有正式事故报告，且没有因此失去唯一关键事实。

满足条件后列入 `DELETE_EXPIRED_LOG` 并实际删除，不复制全量日志到另一目录冒充清理。不满足条件的明确保留原因，不一律写“可能有用”。

检查使用有界读取，不为整理日志再次 `read_text().splitlines()` 全量读取 GB 文件。归档路径变化时按实际位置执行，不写死原路径。

现用 `runtime/logs` 与 `runtime/launcher` 复用已有保留机制。launcher 缺少轮转覆盖时可作最小补齐，但不得截断当前 stdout/stderr、删除正在写的日志或复制一套新的日志系统。

五天 TTL 只用于普通日志与临时调试材料，**不用于备份、已审语料、人工裁定、固定验收记录和故障结案证据**。

---

## 12. 运行资产和审核包：保持原位，逻辑归档即可

以下不是垃圾，本轮不搬散、不全量删除：

```text
runtime/data/
runtime/pids/
runtime/backups/
runtime/review/
runtime/reply-context-fix/
runtime/judge-health-fix-20260921/
runtime/notification-tests/
data/corpus/imports/
data/corpus/reviews/
data/analysis/
```

`runtime/review` 的 16 份回放承担不同模型版本和裁定阶段证据，不是 16 个重复备份。`data/corpus` 保存输入与人工裁定，`runtime/review` 保存程序结果，两者不能互相替代。

当前只有约几十 MiB 的这些资产不作为本轮主要空间回收对象。通过 `runtime/README.md`、`data/corpus/README.md` 和归档索引定位，不为了视觉统一破坏 manifest。

确认为无引用、已过期且完全可重建的临时调试文件可以逐项处理，但必须符合第 9 节，不执行对整棵 runtime/data/corpus 的统一 TTL 清理。

---

## 13. 代码检查：只合并已证实的重复，不凭文件大小重写

清单只指出 `db.py` 约 100 KB、职责集中，没有提供函数级重复证据。Codex 必须先读调用点并形成精简清单，再决定改哪些。

优先检查：

| 领域 | 现有位置／处理方向 |
|---|---|
| 项目根路径和 Python 查找 | PowerShell 复用 `scripts/common-v2.ps1`；Python复用已有 `config.py` 或正式工具，不再分别复制根目录推断。 |
| 版本读取 | 复用 `VERSION` 与现有 `version.py`／构建注入，不继续新增固定版本横幅。 |
| 采集健康 | 保持 `collector_health.py` 为同语义的唯一派生实现。 |
| Judge 规范化与有效性 | 复用正式规范化边界，不在 API、DB、pipeline 分别解析 raw/raw_json，防止再出现字段漂移。 |
| 时间和上下文哈希 | 精确比较未知值、时区和输入版本语义，只合并等价实现。 |
| 日志、脱敏、通知传输 | 复用现有模块；不能为减少文件数合并不同供应商的返回语义。 |
| 前端状态与 API | 保持 src/api.ts、radar-ui.ts 的职责，页面不重复实现 Backend 的业务判断。 |
| Collector 解析 | parser、reply-context、context-observer 之间同语义解析可复用，来源不同的解析不强行合并。 |
| 测试 fixture | 相同构造集中到 conftest/helper；关键场景和断言不能因“相似”而删除。 |

每项实际抽取记录：旧位置、调用者、语义为何等价、目标位置、覆盖测试。**没有证实重复就保留，不为证明自己做过重构而拆模块。**

`db.py` 本轮不强制拆成十几个 repository/service 文件。如确有一个低风险、独立且重复使用的边界，可小幅抽取并维持现有接口；不同时重写事务、Schema、所有 SQL 和任务流程。

不同语言间不为共享几个枚举新增庞大构建系统；用现有契约与回归检查一致性。不同超时／重试语义也不合成“万能工具”。

不得改 Prompt 文本、模型选择、阈值、状态机、周期和通知开关。代码整理后的可观测业务行为应与基线一致。

---

## 14. 所有路径改动必须覆盖真实依赖

对每个 MOVE／DELETE 同步检查：

```text
当前 README、AGENTS、docs 导航与超链接
Python import、__file__ 相对定位、脚本默认路径
PowerShell $PSScriptRoot、common-v2 与 BAT 入口
.env.example 中的默认值（不公开 .env）
Vite/TS/manifest/构建复制路径
pytest 收集路径、fixture、CI 显式文件清单
历史迁移工具的源路径参数
Git ignore 与 tracked 文件状态
浏览器实际加载目录
运行进程 command line 与数据库路径
```

当前用途已迁移时更新当前引用；历史快照中的路径字面量不要全局替换。

避免在忽略整个 `data`、`runtime` 时连可提交的 README、规范或小型测试样例也意外排除；真实资产仍保持忽略。

只在确有短期兼容需求时保留薄包装／重导出，且只有一个实现。不能通过复制源码、复制文档或创建链接目录伪装路径已精简。

---

## 15. 执行顺序与检查点

按以下顺序推进，不把文档、环境和数据库操作一次混改：

1. 固定基线、保护未提交成果、生成处置清单。
2. 检查固定证据和当前路径依赖。
3. 建立 docs 导航，同步当前规范和应用 README。
4. 搬迁允许移动的历史文档及设计资产，验证链接。
5. 检查、合并已证实的少量重复代码，运行对应回归。
6. 集中 `legacy_v1` 源码，验证正式代码不依赖历史目录。
7. 必要时建立并验证 apps/backend/.venv，安全切换；失败就保留旧环境。
8. 核实浏览器、进程与 worktree 后清理旧依赖、构建和临时副本。
9. 按日志白名单清理无保护要求的过期 V1 普通日志。
10. 满足条件再归档剩余 V1 数据，最后删除空旧根目录。
11. 全套正式回归、干净源码检查、有限实际运行验收。
12. 生成一份结项报告，整理提交，停止。

每步可以局部完成。某个固定证据不能移动、旧扩展加载目录暂无法确认，记录保留项即可，不能让整个整理停在“等待用户确认”。真正需要用户操作时一次性汇总。

---

## 16. 验收要求

### 16.1 功能不退化

运行当前实际的 Backend、Web、Collector 测试、类型检查和构建；通知只跑离线 selftest。

重点回归：

```text
root BAT 和 PowerShell 不依赖调用者工作目录
启停只操作本项目进程
新 Python 环境确实被使用（如发生切换）
Judge SQL 读取 → 规范化 → 校验 → API
过期、父帖版本和内容政策继续生效
统一采集健康和有界调度
完整/特殊事件、候选展示和周期幂等
父帖缓存、重处理与资料不足边界
通知非 live 操作绝不发送
Web 读取本地 API，没有恢复 GitHub runtime
```

不重复运行 14 个真实模型窗口，不重新付费跑全库，也不主动触发 DeepSeek。现有日常调度自然发生时单独记录，不把它计为整理必需的测试请求。

实际恢复检查只读健康、最新已存在 Judge 和 Web 代理；需要维护重启时，观察三路新心跳和正常扫描。临时模型失败不应通过调整 Prompt 或颜色“修复”。

本轮微信真实发送 0、邮件真实发送 0。不要运行任何 live 配置检查或把发送通知作为完成提示。

### 16.2 干净源码验证

仅使用拟提交文件在隔离目录验证正式安装说明、导入、测试和构建；不得依赖根目录旧环境、旧 node_modules 或 local-archive 临时工具。可以复用已验证依赖缓存，但如未重新安装，不声称“全新依赖安装通过”。

验证环境阻止真实网络发送和付费模型调用。测试数据库使用临时路径，不读取或修改用户生产库。

### 16.3 文档和数据

- README 两次点击内能找到启动、API、数据规范和通知测试。
- 每个主题只有一个当前正文入口；历史报告仅通过归档索引进入。
- 当前文档无失效本地链接；固定历史路径例外清楚列出。
- 固定证据的路径/哈希保持不变；已审包完整。
- 没有运行数据和凭据进入 Git。
- 记录旧产物、缓存、V1 日志分别实际释放多少字节。
- 逻辑大小与 NTFS 实占用分开；移动和生成归档备份不算释放量。

---

## 17. 提交范围与版本边界

本轮使用独立整理分支或清晰分组提交，按文档归档、代码去重、环境/脚本调整拆分，不混入其他任务未完成的业务修改。

tracked 内容正常记录移动与删除，未跟踪报告先做归属和敏感信息检查；使用显式文件清单，不执行无审查的 `git add .`。

正式源码、测试、当前文档、适合公开的历史报告和脱敏结项说明可以提交。真实语料、数据库、日志、备份、审核包和一次性工具不提交。

本轮默认完成本地整理提交，不自动推送、合并 main、打发布标签或清理远端分支。现有尚未发布的 Judge 修复和微信手动验收不因整理而被宣布完成。

纯文档/路径整理不擅自修改产品版本或 Prompt 版本。代码是否需要后续发布，以现有发布流程决定。

“工作树干净”不是覆盖其他任务修改的理由；清楚列出剩余用户/其他任务成果以及本轮已完成的提交即可。

---

## 18. 本轮只交付一份结项报告

最终位置：

```text
docs/archive/workspace/workspace-optimization-report-20260921.md
```

过程中就维护这一份，不再生成多个 before/after/interim/final 文档。详细逐文件记录留在被忽略的 `runtime/workspace-cleanup-20260921/path-actions.jsonl`。

最终摘要：

```text
总体：PASS / PARTIAL / BLOCKED

日常入口：
README ...
当前文档 ...
通知测试 ...

文档：
保持当前 ...
归档 ...
合并重复正文 ...
固定证据原位保留 ...
当前坏链接 ...

代码：
实证重复及复用位置 ...
legacy 集中 ...
未做不必要架构重写 ...

旧目录：
backend：环境/数据分别如何处理
dashboard：已删或保留原因
extension：实际加载核查与处理
_tmp：普通副本/worktree/策略阻塞分别处理

空间：
旧依赖/构建实际删除 ...
V1 普通过期日志实际删除 ...
缓存/临时副本实际删除 ...
移动/归档但未释放 ...
明确保留的数据库与审核证据 ...

运行：
真实 Python 路径 ...
Backend / Web ...
Profile / Replies / Search ...
实际数据库位置 ...

测试：
Backend ...
Web ...
Collector ...
通知离线 ...
干净源码 ...

安全：
真实通知发送 0
未主动调用模型
固定证据未损坏
凭据/真实数据未提交

Git：
整理分支/本地提交 ...
其他未提交成果 ...
未推送、未发布 ...

报告：
准确路径
剩余保留/阻塞项：
逐项列原因，不泛泛写“可能有用”
```

**停止条件：当前入口清楚、普通历史报告集中、固定证据可追溯、已证实无用的副本和过期普通日志得到处理、功能不退化。保留一个仍有真实依赖的旧路径可以接受；为了让目录树好看而破坏启动、采集或数据不可以。**

完成后停止，不继续开发新的通知、语料、Dashboard 或服务器能力。
