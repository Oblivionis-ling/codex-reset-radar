# Codex Reset Radar — Phase E.5 进度报告

报告时间：2026-08-31 04:10（Asia/Shanghai）
阶段：Phase E.5 — Live Data Mirror & Health Semantics Fix

## 1. 阶段结论

Phase E.5 的代码、测试和线上数据链路已完成。Dashboard 与运行时数据
更新已经分离：Pages 只在 `main` 源码变化时重新部署，Dashboard 运行时从
GitHub `data` 分支读取最新公开 JSON。

## 2. Root Cause

旧实现把 `main/public-data/` 在构建时复制进 Pages artifact。之后本地
SQLite 和心跳继续更新，但线上静态文件不会变化。快照超过原有时间阈值
后，Dashboard 又把“旧快照”直接解释成四路 Monitor `offline`，因此出现
“全部 offline”。这不能证明本地 Monitor 当时真的掉线。

本阶段将两种事实拆开：

```text
本地 Monitor 报告的 state
+
公开快照本身的 freshness
```

Dashboard 现在只在 fresh 快照明确报告 `offline` 时显示离线；stale 快照
统一显示 `数据过期 / 最后已知状态`，缺字段或无法判断时显示 `未知`。

## 3. Data Branch

GitHub 仓库：<https://github.com/Oblivionis-ling/codex-reset-radar>
Live branch：`data`
Raw base：<https://raw.githubusercontent.com/Oblivionis-ling/codex-reset-radar/refs/heads/data/>

分支当前只保留五个文件：

```text
index.json
tweets.json
radar.json
health.json
meta.json
```

同步脚本先用 SQLite read-only 导出，再在独立临时 worktree 中提交并推送，
不会切换当前开发工作区，也不会自动修改 `main/public-data/`。Backend
使用轻量 asyncio scheduler：正常周期为 5 分钟，事件触发可提前运行；每
周期最多 3 次 push retry。GitHub 失败只记录日志并等待下一周期，不影响
Collector、DeepSeek、Radar、SQLite 或 WxPusher。

## 4. Sync Tests

使用本地 bare Git remote 做可重复测试，修复了 PowerShell 将 Git push 的
正常 stderr 状态输出误判为失败的问题。修复后连续三个周期结果如下：

| 周期 | sync exit | data branch 结果 |
|---:|---:|---|
| 1 | 0 | commit 创建，五个 JSON 存在 |
| 2 | 0 | commit 创建，五个 JSON 存在 |
| 3 | 0 | commit 创建，五个 JSON 存在 |

远程 bare branch 的 commit count 连续递增，最终 tree 仅包含上述五个文件。
Exporter 回归验证为 124 条 Tweet、四路 Monitor 状态均能按数据库真实值
导出；旧 heartbeat 年龄不会被 exporter 改写成 `offline`。

## 5. Dashboard 与线上数据

Dashboard 生产配置集中在 `dashboard/src/config.ts`，从 `data` branch 的
Raw URL 读取 JSON；每 60 秒自动刷新，所有请求使用 `cache: "no-store"`。
刷新失败会保留上一次成功数据并显示提示，缺字段、空信号、缺 Health 组件
和初始请求失败均不会白屏。

已验证：

- GitHub Raw `refs/heads/data` 下的五个 JSON 均返回 HTTP 200；
- Raw `meta.json` 的 `generated_at` / `mirror_synced_at` 可解析，当前线上
  快照为 124 条 Tweet、Radar `CONFIRMED`、四路 health `healthy`；
- GitHub Pages 首页返回 HTTP 200，Pages 模式为 workflow；
- data branch 更新不会触发 `tests` 或 `Deploy dashboard` workflow。最近的
  Pages 与 CI 运行均由 `main` push 触发，`ci.yml` 现在只监听 `main` push
  和 Pull Request，`pages.yml` 只监听 `main` push 和手动触发；
- `npm test`：5 passed；`npm run build`：通过；构建产物未包含 Secret、
  `.env` 或本机地址。

页面是否需要 redeploy 的判断规则也已明确：Pages deploy 时间可以不变，
只要页面下一次 60 秒刷新读取到 data branch 新的 `meta.json` / `health.json`
即可。生产 Raw 数据与 Pages artifact 已完全分离。

## 6. Health Semantics 验证

前端 `deriveDisplayHealth()` 和 Data Mirror freshness 函数已覆盖：

| 输入 | Dashboard 显示 |
|---|---|
| fresh + healthy | `healthy` / 正常 |
| fresh + offline | `offline` / 离线 |
| stale + healthy | `stale` / 数据过期，最后已知正常 |
| stale + offline | `stale` / 数据过期，最后已知离线 |
| 缺少 component 或 freshness | `unknown` / 未知 |
| 单文件 fetch 失败 | 保留该文件上次成功值，不白屏 |

前端测试覆盖了 `cache: no-store`、meta 解析、刷新失败保留旧数据、空信号、
15 分钟 freshness 及上述五种 Health 语义。Backend exporter 测试覆盖了
stale snapshot 下保留数据库报告的 raw state。

## 7. Automated Tests

本阶段最终回归：

- Backend：**28 passed**；
- Dashboard：**5 passed**；
- Dashboard TypeScript/Vite build：**通过**；
- PowerShell parser：**通过**；
- `npm audit --omit=dev`：Phase E 基线为 **0 vulnerabilities**；
- Extension 与既有 Phase A–D 回归保持通过。

## 8. Final Online Check

检查对象：<https://oblivionis-ling.github.io/codex-reset-radar/>
检查时间：2026-08-31 约 04:10（Asia/Shanghai）

线上可访问、可读取公开 Raw JSON，数据快照为：

```text
generated_at / mirror_synced_at: 2026-08-30T20:03:04Z
tweet_count: 124
radar: CONFIRMED
health: backend/profile/replies/search_backfill = healthy
```

该快照距检查时间约 7 分钟，处于 15 分钟 fresh 窗口；页面应按四路公开
状态显示正常。此前用旧快照测试 stale 规则时，页面显示的是`数据镜像过期`
而不是把四路 Monitor 直接改成离线。GitHub Actions 最近成功的 Pages 部署
和 CI 运行均对应 `main`，data branch 更新不触发新的 Pages 构建。

## 9. 安全与范围

本阶段没有新增 Cloud Backend、数据库、服务器、WebSocket、登录系统、复杂
图表或通知渠道。Dashboard 不访问本机，不保存 GitHub Token、DeepSeek Key
或 WxPusher Token。当前停止在 Phase E.5 验收点，不继续扩展后续功能。
