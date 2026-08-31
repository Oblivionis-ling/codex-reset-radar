# Phase F 进度报告

日期：2026-08-31  
项目：Codex Reset Radar  
基线：Phase E.5 live data mirror + GitHub Pages Dashboard

## 结论

Phase F 的代码、数据契约、翻译 backfill、静态页面和本地验收已完成。Dashboard 已改为中文优先，保留英文切换，并新增 `#/tweets` 与 `#/resets` 两个 GitHub Pages 兼容页面。

GitHub `data` 分支已由现有 mirror scheduler 成功同步新数据；本轮 `main` push 因当前环境连接 GitHub:443 失败，Pages 的代码部署尚未能由本轮完成。当前线上 Pages URL 仍可能展示上一版 Dashboard，待 `main` commit `ba2062c` 成功推送后，等待 Pages workflow 完成即可。

## Translation

- 存储位置：`tweets` 表新增 `translated_zh`、`translation_model`、`translation_version`、`translated_at`；原始 `text` 永不覆盖。
- Provider：复用现有 DeepSeek Provider 和 `DEEPSEEK_MODEL=deepseek-v4-flash`，新增本地 translation prompt；前端不访问 AI。
- 缓存：`translation_version` 未变化且已有翻译时跳过调用。
- Backfill 目标：最近 20 条 Tweet + 所有 Reset/额度高价值信号，共 34 条。
- 结果：30 条成功，4 条因 DeepSeek 请求超时失败；失败项保留英文原文，Dashboard 显示“翻译暂不可用”。
- 运行入口：`scripts/translate_backfill.py`；新 Tweet 的分类完成后会 best-effort 自动翻译。
- 翻译失败不会影响 Collector、Classification、Radar、通知或 GitHub mirror。

## Localization Audit

已完成：

- Radar、额度建议、Health、Freshness、导航、按钮、空状态、错误提示、分类、紧急度、表头和日历均提供中文显示。
- 中文界面默认显示中文，右上角可切换 English，选择保存在浏览器本地。
- Tweet 卡片主显示中文翻译，下方显示英文原文；原文和 X 链接保留。
- 允许保留的英文：Codex、Tibo、DeepSeek、GitHub、X、ChatGPT Work、Plus、Tweet/Reset 等产品或领域名词。

## Reset Forecast

优先级：明确公告时间 > `reset_hint + within_24h` > 最近确认 Reset + 7 天。

当前真实数据：

- Last confirmed Reset：`2026-08-31T02:34:27Z`（北京时间 2026-08-31 10:34）。
- Ground Truth 来源：最新 Final `reset_confirmed` Tweet；显式 `reset_events` 为空时才启用该只读派生。
- Baseline next Reset：`2026-09-07T02:34:27Z`。
- 当前 active signal：无尚未过期的高优先级 hint/可解析 announcement。
- Final estimate：`2026-09-07T02:34:27Z`。
- Forecast source：`weekly_baseline`。

`reset_confirmed` 的近重复证据已合并；当前公开 Reset 历史样本数为 4。`reset_hint` 和 `reset_announcement` 不会被当作已经发生的 Reset。

## Usage Advice

当前 Radar：`CONFIRMED`。  
当前建议：`GREEN` — “重置已确认，可检查额度是否刷新”。

建议逻辑统一由后端 `derive_usage_advice()` 产生：

- GREEN：正常使用；CONFIRMED 特殊显示可检查额度刷新。
- YELLOW：WATCH 或距离基础估算不超过 48 小时。
- ORANGE：LIKELY 或预计不超过 24 小时。
- RED：IMMINENT / ANNOUNCED。

提示文案使用“建议/可以考虑/优先”，不使用“必须立刻”。

## Public Data

已更新：

- `tweets.json`：增加 `translation_zh` 等可选附加字段。
- `radar.json`：增加 `forecast`、`usage_advice`。
- 新增 `resets.json`：确认 Reset 历史、北京时间、间隔、样本数和轻量时间分布。
- `docs/public-data-contract.md`、Vite public-data 插件和 GitHub data sync required files 已同步更新。

data 分支线上验收：

- `meta.json` 返回 `last_sync_status=success`。
- `resets.json` 可正常读取，当前 `sample_count=4`。
- `radar.json` 返回上述 Forecast 和 GREEN usage advice。

## Pages

- `/`：当前 Radar、额度使用建议、最近/预计 Reset、最新 1–3 条高价值信号、Health 和 Data Mirror。
- `/#/tweets`：最近 20 条 Tweet，按发布时间倒序，包含中文翻译/不可用提示、英文原文、分类、置信度、紧急度、是否回复和 X 链接。
- `/#/resets`：Reset 历史、北京时间轻量日历、点击日期详情、时间分布、样本数和 Reset 间隔。
- 使用 hash routing，兼容 GitHub Pages 直接打开页面。

## Tests and Acceptance

| 检查项 | 结果 |
|---|---:|
| Backend pytest | 33 passed |
| Dashboard Vitest | 5 passed |
| Extension Vitest | 12 passed |
| Dashboard TypeScript/build | passed |
| Extension MV3 build | passed |
| PowerShell parser | passed |
| `npm audit --audit-level=high` | 0 vulnerabilities |
| 390px 移动布局 | 通过，无横向溢出 |
| 中文默认/英文切换 | 通过 |
| `/tweets`、`/resets` hash route | 通过 |
| 日历点击日期详情 | 通过 |
| public-data 请求失败降级 | 既有测试通过 |
| bundle Secret/localhost 扫描 | 未发现 |

## Runtime Note

本轮已完成数据库无损 migration 和一次性翻译 backfill；现有常驻 Backend 进程没有被强制终止。要让“新 Tweet 分类后自动翻译”在常驻进程中立即生效，需要在确认窗口后按既有方式重启 Backend；数据库字段和已完成的 backfill 不受影响。现有旧进程仍可继续执行公开 mirror，data 分支已成功收到新契约数据。

## 停止点

Phase F 范围已停止在中文信息体验、Forecast、额度提示、Reset 历史和静态 Pages Dashboard。未新增账号系统、多用户、复杂统计模型、机器学习预测、新服务器或新云服务。
