# Codex Reset Radar — Live Mirror 到 Dashboard 接收诊断报告

报告日期：2026-09-02（Asia/Shanghai）  
证据时间窗口：2026-09-01 UTC  
诊断范围：Backend GitHub data mirror、GitHub Pages Dashboard 刷新与数据新鲜度。

## 1. 最终结论

本次提供的前端历史记录中，没有发现 Backend 镜像发布到 Dashboard 接收超过 15 分钟的情况。

但是，Backend 历史成功发布记录中确实存在多次超过 15 分钟的成功发布间隔。因此，Dashboard 出现数据年龄增长或过期状态的根因在于：

> Backend 没有及时产生新的成功 GitHub mirror 发布；Dashboard 本身仍按每分钟正常请求并成功接收了公开数据。

本次证据不支持以下判断：

- Dashboard 请求链路耗时超过 15 分钟；
- GitHub Pages 前端刷新 timer 停止；
- 前端收到新数据后延迟渲染；
- 前端 HTTP 请求失败导致页面使用旧快照。

## 2. 监控链路

```text
Backend mirror scheduler
  -> public export / git push
  -> data branch meta.json mirror_synced_at
  -> Dashboard 每 60 秒发起刷新
  -> index / radar / health / resets / meta / tweets 返回
  -> Dashboard 记录 dashboard_received_at
  -> 页面根据 used_snapshot_at 判断 freshness
```

本报告区分三个时间概念：

| 指标 | 含义 |
|---|---|
| Backend successful publish interval | 两次成功写入 data branch 的 `mirror_synced_at` 之间的间隔 |
| Dashboard request duration | Dashboard 一次刷新从请求开始到全部 JSON 返回的耗时 |
| Snapshot age at receipt | `dashboard_received_at - mirror_synced_at`，即页面收到的数据有多旧 |

其中第三项超过 15 分钟会触发 freshness stale；它不等于前端网络请求耗时。

## 3. 证据来源

### Backend

```text
D:\work\20260828-CodexResetRadar\backend\data\mirror-cadence.jsonl
```

日志统计范围：

- 首条日志：`2026-09-01T04:49:31.737495Z`
- 末条日志：`2026-09-01T17:42:50.983770Z`
- JSONL 记录：446 条
- scheduler cycle started：153 次
- scheduler 来源的失败记录：73 次

### Dashboard

来源为用户从 Dashboard 浏览器 `localStorage["codex-reset-radar-refresh-log"]` 导出的 8 条记录。

前端记录范围：

- 首次接收：`2026-09-01T17:42:12.338Z`
- 最后接收：`2026-09-01T17:49:11.753Z`
- 8 条全部为 `result=success`
- 每条均包含 6 个 JSON 文件的 HTTP 状态
- 8 条记录均无错误，全部文件均为 HTTP 200

## 4. Dashboard 历史接收分析

这 8 次刷新全部使用同一个公开快照：`2026-09-01T17:37:08Z`。

| Dashboard 接收时间 | 快照时间 | 快照年龄 | 刷新耗时 |
|---|---|---:|---:|
| 17:42:12.338Z | 17:37:08Z | 5分04.338秒 | 809 ms |
| 17:43:12.329Z | 17:37:08Z | 6分04.329秒 | 462 ms |
| 17:44:11.751Z | 17:37:08Z | 7分03.751秒 | 213 ms |
| 17:45:12.089Z | 17:37:08Z | 8分04.089秒 | 222 ms |
| 17:46:12.360Z | 17:37:08Z | 9分04.360秒 | 500 ms |
| 17:47:11.758Z | 17:37:08Z | 10分03.758秒 | 215 ms |
| 17:48:11.937Z | 17:37:08Z | 11分03.937秒 | 394 ms |
| 17:49:11.753Z | 17:37:08Z | 12分03.753秒 | 211 ms |

统计结论：

- 最大 snapshot age：12分03.753秒；
- 超过 15 分钟：0 条；
- Dashboard 单次刷新耗时范围：211–809 ms；
- 前端刷新没有出现 15 分钟级别的 HTTP 等待。

以 Backend 对应成功记录的本地日志时间 `2026-09-01T17:37:13.900650Z` 作为发布完成时间近似值计算：

- 首条前端记录相差：4分58.437秒；
- 最后一条前端记录相差：11分57.852秒；
- 超过 15 分钟：0 条。

## 5. Backend 历史成功发布间隔

按 `PUBLIC_MIRROR_EXPORT_COMPLETED` 中同时存在 `mirror_synced_at` 和 `push_attempt=1` 的记录推断成功发布，共得到 80 次成功发布。

历史上共有 10 个成功发布间隔超过 15 分钟：

| 上一次成功 | 下一次成功 | 间隔 |
|---|---|---:|
| 07:27:08Z | 07:52:08Z | 25 分钟 |
| 08:02:08Z | 08:27:08Z | 25 分钟 |
| 10:27:08Z | 11:02:08Z | 35 分钟 |
| 11:57:08Z | 12:22:08Z | 25 分钟 |
| 12:32:08Z | 12:52:08Z | 20 分钟 |
| 12:52:08Z | 13:12:08Z | 20 分钟 |
| 13:12:08Z | 13:37:08Z | 25 分钟 |
| 13:52:08Z | 14:17:08Z | 25 分钟 |
| 15:17:08Z | 15:47:08Z | 30 分钟 |
| 17:12:08Z | 17:37:08Z | 25 分钟 |

总体统计：

- 成功发布次数：80；
- 成功间隔最短：约 4分59秒；
- 成功间隔平均：约 9分37秒；
- 超过 7 分钟的间隔：28 次；
- 超过 15 分钟的间隔：10 次；
- 最大成功间隔：35 分钟。

## 6. 17:37–17:49 事件时间线

与前端历史直接对应的 Backend 事件如下：

| 时间 | 事件 | 结果 |
|---|---|---|
| 17:37:08Z | scheduled cycle started | 开始 |
| 17:37:08Z | mirror snapshot generated | 成功快照 |
| 17:37:13.900650Z | Backend 记录成功发布 | 成功记录 |
| 17:42:08Z | scheduled cycle started | 开始 |
| 17:42:50.983770Z | GitHub mirror sync | 失败 |
| 17:42:12–17:49:11Z | Dashboard 每分钟刷新 | 均成功，但仍读取 17:37:08 快照 |

17:42 的失败原因包含：

```text
Could not connect to github.com:443
```

以及连接被重置等 GitHub 网络错误。

这解释了为什么 Dashboard 继续正常响应，却持续显示同一个 `17:37:08Z` 的数据快照。

## 7. 根因判断

### 已确认

1. scheduler cycle 本身大致按 5 分钟启动；
2. 部分 cycle 在 GitHub clone/push 阶段失败；
3. 失败会造成成功发布之间出现 20–35 分钟空窗；
4. Dashboard 每分钟刷新没有停止；
5. Dashboard 请求耗时为毫秒级；
6. Dashboard 在本次历史记录中没有丢失数据，也没有出现 HTTP 错误；
7. 当前 Dashboard 的 freshness 判断是正确的：17:49 时快照年龄约 12 分钟，仍未超过 15 分钟。

### 未确认或本次无法证明

- GitHub 连接失败是否完全由本机网络、GitHub 服务端或代理链路引起；
- 17:49 之后是否继续存在相同失败，因为提供的前端历史在 17:49 截止；
- 更早时间段中是否存在 Dashboard 接收超过 15 分钟的记录，因为当前提供的前端导出只覆盖 17:42–17:49。

## 8. 日志审计限制

当前 JSONL 中实际出现的事件类型主要是：

- `PUBLIC_MIRROR_CYCLE_STARTED`
- `PUBLIC_MIRROR_EXPORT_COMPLETED`
- `PUBLIC_MIRROR_SYNC_FAILED`

本次日志没有稳定出现独立的 `PUBLIC_MIRROR_PUSH_STARTED` 和 `PUBLIC_MIRROR_SYNC_SUCCESS` 记录。因此，Backend 的 80 次成功发布是依据以下组合字段推断的：

```text
event = PUBLIC_MIRROR_EXPORT_COMPLETED
mirror_synced_at != null
push_attempt = 1
```

`backend_logged_at` 可用于当前关联分析，但不能完全替代真正的 GitHub push 完成时间。后续若需要严格证明“push 完成 → Dashboard 收到”的延迟，应让 Backend 在 push 成功返回后单独写入一条不可混淆的 `PUBLIC_MIRROR_SYNC_SUCCESS`，并使用该事件的 `sync_finished_at`。

## 9. 诊断结论等级

| 问题 | 结论 |
|---|---|
| Dashboard 是否接收超过 15 分钟 | 本次 8 条历史记录中没有 |
| Dashboard 请求是否变慢 | 没有，211–809 ms |
| Backend 是否出现超过 15 分钟成功发布间隔 | 是，10 次，最长 35 分钟 |
| 17:42–17:49 的页面是否持续收到数据 | 是，每分钟一次 |
| 数据过期风险来自哪里 | Backend mirror 成功发布中断 |
| 是否应把 stale threshold 改为 30 分钟 | 不应改，15 分钟阈值仍然有效 |

## 10. 建议

1. 保持 Dashboard 的 `fresh <= 15min`、`stale > 15min` 规则不变。
2. 保持 Dashboard 每 60 秒刷新；当前前端刷新链路无需修复。
3. 继续修正 Backend mirror 事件拆分，确保明确记录 `PUSH_STARTED` 与真正的 `SYNC_SUCCESS`。
4. 对 GitHub 443 连接失败单独统计网络失败、clone 失败、push 失败和 retry 次数。
5. 后续验收应同时提供 Backend 成功发布日志和 Dashboard localStorage 导出，分别计算“发布间隔”和“页面收到的快照年龄”。
6. 不要把 Backend 的成功发布空窗误报为 Dashboard HTTP 接收延迟。

## 11. 本报告未做的事情

本次仅做日志分析和根因诊断，没有：

- 修改 Collector；
- 修改 health threshold；
- 修改 Dashboard freshness threshold；
- 实现自动 reload、自动重开 Tab 或 self-healing；
- 修改 DeepSeek、Radar、Alert Manager 或 WxPusher；
- 新增 Backend、数据库或云服务。
