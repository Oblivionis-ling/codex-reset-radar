# Codex Reset Radar 第一阶段进度汇报

汇报时间：2026-08-28 17:41（Asia/Shanghai）

## 一、结论

当前项目已经进入可运行状态，但 Phase A 还不能标记为“全部验收通过”。

- Milestone 0：完成并通过测试。
- Milestone 1：代码完成，Profile 和 Replies 已在当前 Edge 登录会话中现场跑通。
- Milestone 2：代码完成，Search Backfill 已在当前 Edge 登录会话中现场跑通。
- 当前没有开发 AI、通知、GitHub mirror 或 Dashboard，符合任务书的阶段顺序。

## 二、当前部署状态

### Backend

本地 Backend 正在运行：

```text
http://127.0.0.1:8787
```

健康接口当前返回：

```text
status: ok
tweets: 46
```

### Edge Extension

扩展已经成功注入当前 Edge 的 X 页面，因为 Backend 已收到 Profile 和 Replies 两路心跳及 Tweet 数据。

当前健康状态：

| 组件 | 状态 | 现场证据 |
|---|---|---|
| Backend | healthy | 最近心跳 age 约 0 秒 |
| Profile Monitor | healthy | 最近心跳 age 约 0 秒 |
| Replies Monitor | healthy | 最近心跳 age 约 31 秒 |
| Search Backfill | healthy | 最近心跳约 31 秒前，已产生 `search` source 记录 |

## 三、实际采集结果

- SQLite 中共有 46 条唯一 Tweet。
- 其中 11 条被 Profile Monitor 发现。
- 其中 12 条被 Replies Monitor 发现。
- 其中 46 条被 Search Backfill 发现。
- 21 条 Tweet 被多个来源发现，最终仍只有一条数据库记录。
- 当前已确认去重的 Tweet ID：
  - `2093207246977318928`
  - `2093207264194892263`
- Replies 页面当前已经产生 12 条数据，其中 12 条被标记为 reply。

这证明了第一阶段最核心的链路：

```text
Edge DOM → localhost HTTP → FastAPI → SQLite → tweet_id 去重
```

## 四、自动化验证

- Backend：3 passed
  - Profile/Search/Replies 同一 Tweet 去重与多来源记录
  - Backend health 与 monitor heartbeat
  - 八张核心/预留 SQLite 表存在
- Extension：5 passed
  - Tweet DOM 解析
  - 嵌套引用 Tweet 过滤
  - Reply target 提取
  - DOM 结构 fallback
  - 72 小时 UTC 搜索窗口生成
- TypeScript：通过
- MV3 build：通过，产物位于 `extension/dist`
- 运行时依赖审计：production dependencies 0 vulnerabilities

## 五、任务书对照

### 已完成

- 本地 FastAPI + SQLite 单体 Backend
- Manifest V3 + TypeScript + Vite Extension
- Profile DOM Monitor
- `/with_replies` Monitor
- MutationObserver
- 60 秒 fallback scan
- X numeric Tweet ID 提取
- Tweet 标准化
- SQLite `UNIQUE(tweet_id)` 去重
- `tweet_sources` 多来源记录
- Backend heartbeat 与组件健康状态
- Backend 不可用时 Extension 本地 pending queue 重试
- 72 小时 Search Backfill 代码与 UTC 分日查询逻辑
- 7 天低频 reconciliation 代码
- `.env.example` 与本地安全约束
- `start-radar.bat`

### 尚未完成或尚未验收

- 7 天低频 Deep Backfill 尚未等待到第一个 6 小时周期，代码已完成但尚未单独现场确认。
- 还没有故意执行 Chrome/Edge 页面刷新后的恢复测试。
- 还没有故意执行 Backend 重启后的恢复测试。
- 还没有计算真实漏报率，因为目前还没有人工标注的完整 Tweet 基线。
- Replies 和 Search 的真实行为仍受 X 页面登录状态、页面错误和 DOM 变化影响。

## 六、当前风险

1. **仍需完成恢复性验收。** 还没有故意执行页面刷新和 Backend 重启测试。
2. **X DOM 变化风险。** 当前使用语义 selector、`article` 和 status link fallback，并不能保证长期不受 X 改版影响。
3. **虚拟化列表风险。** 只能采集 X 实际渲染到 DOM 的 Tweet；后台 Search 会滚动六个 viewport，但仍可能遗漏更深结果。
4. **浏览器后台节流风险。** Chrome/Edge 可能延迟 alarm 或后台标签页执行。
5. **当前没有 AI 判断。** 现在只负责可靠采集，不会把 Tweet 自动判断为 Reset，也不会发送 Reset 预警。

## 七、下一步验收顺序

1. 关闭并重新打开 Profile 页面，确认心跳和数据继续工作。
2. 重启 Backend，确认 Extension pending queue 能重新提交。
3. 等待一个 6 小时周期，单独确认 7 天 Deep Backfill。
4. Search、刷新、重启三项通过后，进入 Phase B 的 Rule Classifier 和 DeepSeek Provider。
