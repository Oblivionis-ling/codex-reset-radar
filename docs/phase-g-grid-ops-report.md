# Codex Reset Radar — Phase G Grid Ops Dashboard 报告

日期：2026-08-31
阶段：Phase G — Grid Ops Dashboard 视觉重构
基线：Phase F `ab88bff`

## 结论

Phase G 的 Dashboard 视觉重构已在本地完成，业务数据与路由保持不变。首页、Tweets、Resets 三个页面统一为高密度 Grid Ops 控制台：深蓝固定侧栏、纸张白背景、二维硬网格、独立 Radar / Confidence / Urgency 指标、Ops Matrix 和移动端紧凑导航。

本轮没有修改 Collector、Backend 业务逻辑、SQLite、分类、Radar、Forecast、Usage Advice、Health 语义、Reset 数据契约、GitHub Mirror 或通知链路。

## Preflight

| 项目 | 状态 |
|---|---|
| Phase F `main` | 已推送，`HEAD` 与 `origin/main` 均为 `ab88bff` |
| 本地 Backend | `http://127.0.0.1:8787/health` 返回 200；现有常驻进程仍在运行 |
| Backend 重启 | 本阶段未强制终止现有进程；不影响本次前端构建，翻译运行时是否已切换仍按 Phase F 运行说明处理 |
| 本地公开快照 | 当前 `public-data/meta.json` 为旧样本快照，页面正确显示“数据镜像过期 / 最后已知状态” |
| Phase G Pages | 已部署；远程 `main` 为 `7551779`，`Deploy dashboard` workflow 成功 |
| Git push | Git transport 两次因当前环境连接 `github.com:443` 超时；使用已登录 GitHub CLI API 创建等价远程 commit 完成发布 |

当前真实前端 fixture 保持：Radar `CONFIRMED`、confidence `99%`、urgency `now`、Usage Advice `GREEN`、最近一次确认 Reset 为北京时间 2026-08-31 10:34、下一次周期估算为 2026-09-07 10:34。

## Design Tokens

- 颜色：`--paper #f7f7f2`、`--blue #102a72`、`--blue-deep #071b4d`、`--yellow #ffb11b`、`--red #e84a4a`、`--light-blue #dce5f5`。
- 字体：Fira Sans / 系统无衬线用于正文，Fira Code / Consolas / 等宽 fallback 用于时间、百分比、状态码、Tweet ID 和同步信息。
- 间距：以 8px 节奏为主，区块间距 14px，内容区自适应内边距。
- 边框：主要结构使用 1px 深蓝或浅蓝分隔线；状态提示使用硬边框。
- 圆角与阴影：结构基本为 `0px` 圆角，无阴影。
- 视觉限制：无 gradient、glassmorphism、blur、glow、emoji、大面积圆角 SaaS Card 或装饰性图表。

## Layout

- Desktop：约 248px 固定左侧栏，右侧为 sticky top bar 和完整 Grid 内容区；Radar 状态占首页第一视觉区最大面积。
- Tablet：在 1080px 以下压缩侧栏与内容边距；768px 仍保留二维网格和可读指标。
- Mobile：760px 以下移除固定侧栏，使用顶部三项导航；390px 下 Radar、Confidence、Urgency、建议、Reset 日期仍按信息优先级排列。
- 页面保留 hash routing：`/#/`、`/#/tweets`、`/#/resets`。
- 增加键盘可用的“跳转到主要内容”链接；按钮、链接、日历日期继续使用原生语义和可见 focus 状态。

## Overview

首页保留 Phase F 既有业务结构并调整视觉层级：

- Radar：巨大状态文字、原始状态码、判断原因、更新时间和 stale 时的“最后已知状态”。
- Confidence / Urgency：独立指标格，沿用 Phase F 的真实映射。
- Last / Next Reset：显示北京时间、来源或估算依据及相对时间。
- Usage Advice：作为强边框操作建议模块；`GREEN` 映射为蓝色信息层，避免把 `CONFIRMED` 误做成全页事故红色。
- Latest Signal：首页只显示最多 3 条高价值真实 Tweet；中文翻译优先，翻译缺失显示“翻译暂不可用”并保留英文原文。
- Monitor Health：四路组件改为 Ops Matrix，单独展示状态、最后心跳和心跳年龄；stale 快照显示“数据过期”并保留最后已知状态。
- Data Mirror：独立展示 data branch、freshness、最后同步时间，不把镜像过期误解释为 Monitor offline。

## Tweets

`/#/tweets` 改为高密度事件档案列表，读取真实 `tweets.json` 最近 20 条并按发布时间倒序。每行保留时间、Tweet / Reply、分类矩形标签、urgency、confidence、中文翻译、英文原文、判断原因、Tweet ID 和 X 原帖链接；没有翻译时不造成空白或布局塌陷。

## Resets

`/#/resets` 保留真实 `resets.json` 的小样本语义：

- Reset Calendar 使用 7 列方形日期格和 1px 网格；已发生日期带有明确 `RESET` 标识，点击日期后更新详情。
- Time Distribution 使用四段 CSS 水平条，数量直接读取公开数据。
- Reset History 独立表格保留日期、北京时间、间隔、来源和真实 X 证据链接；不在前端重复 deduplicate。
- 页面明确显示当前 `sample_count = 4`，不把小样本渲染成高权威统计。

## Localization Audit

- 默认语言保持中文，并通过 localStorage 保留用户选择；英文切换覆盖 Overview、Tweets、Resets。
- 中文页面已检查 Radar、建议、Health、freshness、导航、按钮、空状态、错误提示、分类、紧迫度、表头和日历。
- 允许保留的产品和技术名词包括 Codex、Tibo、X、GitHub、DeepSeek、ChatGPT Work、Plus、Tweet、Reset 和状态码。
- 刷新按钮文案为中文“刷新数据”，英文为 `REFRESH DATA`；没有使用“立即同步 / SYNC NOW”。

## Responsive Acceptance

| Viewport | 结果 |
|---:|---|
| 1440px | 通过；固定侧栏、Radar 第一视觉区和 Ops Matrix 正常 |
| 1280px | 通过；Grid 内容区无横向溢出 |
| 768px | 通过；压缩后的桌面布局保持可读 |
| 390px | 通过；顶部导航、Radar 大字和核心指标无横向溢出 |

验收截图：

- [中文 Desktop 首页](phase-g-screenshots/overview-zh-desktop.png)
- [English Desktop 首页](phase-g-screenshots/overview-en-desktop.png)
- [中文 Tweets](phase-g-screenshots/tweets-zh-desktop.png)
- [中文 Resets](phase-g-screenshots/resets-zh-desktop.png)
- [390px 中文首页](phase-g-screenshots/overview-zh-mobile.png)

## Tests

| 检查项 | 结果 |
|---|---:|
| Backend pytest | 33 passed（1 个既有 Starlette deprecation warning） |
| Dashboard Vitest | 7 passed |
| Dashboard TypeScript / Vite build | passed |
| Extension Vitest | 12 passed |
| Extension TypeScript | passed |
| Extension MV3 build | passed |
| PowerShell parser | passed |
| Dashboard / Extension production dependency audit（`--omit=dev`） | 0 vulnerabilities |
| 1440 / 1280 / 768 / 390px 浏览器验收 | passed |
| English 切换、`#/tweets`、`#/resets` | passed |
| 日历点击日期详情 | passed |
| stale / empty signals / missing health fixture | passed（既有测试） |
| Dashboard bundle Secret / localhost 扫描 | passed（仅审查 JS/CSS；公开数据中的 `deepseek-v4-flash` 仅为模型名，不是 Secret） |

扩展开发依赖的 `npm audit` 仍会报告 Vite 5 / esbuild 的开发工具链 advisory；扩展没有生产依赖，本次未引入破坏性升级，生产依赖审计为 0 vulnerabilities。

## Online

目标地址：[https://oblivionis-ling.github.io/codex-reset-radar/](https://oblivionis-ling.github.io/codex-reset-radar/)

线上验收已完成：

- 根页 HTTP 200，确认加载 Phase G Grid Ops shell；首次验收浏览器以中文默认加载。
- 中文首页：Radar、Confidence、Urgency、Usage Advice、四路 Monitor Health 和 Data Mirror 均可读取。
- English 切换：`lang=en`、`REFRESH DATA` 和英文页面标题正常。
- `/#/tweets`：中文标题、20 条 Tweet、20 个真实 X 原帖链接正常。
- `/#/resets`：中文标题、31 个日历日期格、4 条 Reset History 记录和 `sample_count=4` 正常。
- 线上当前 data branch 快照为 fresh，四路 Monitor 显示正常；页面仍从 Raw JSON 读取公开数据，不访问本机，不携带任何 Secret。

GitHub Actions：`tests` run `33372153913` success；`Deploy dashboard` run `33372153912` success。data branch 更新仍不要求 Pages 重新部署。

## 停止点

Phase G 范围停止在 Dashboard 视觉、布局、交互、可访问性、响应式和线上部署验收。没有继续开发账号系统、复杂图表、额外云服务、Backend、Collector 或通知系统。
