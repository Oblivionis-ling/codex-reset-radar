# Codex Reset Radar — Profile / Replies SPA Route Fix 报告

## 1. 验收范围

- 验收日期：2026-08-31（Asia/Shanghai）
- 目标：修复 X SPA 导航到 `/thsottiaux/status/<tweet_id>` 时 Profile / Replies monitor context 丢失的问题。
- 本次未修改 Collector、60 秒 heartbeat/fallback interval、15/30 分钟 health threshold、通知链路或 self-healing。

## 2. Root Cause

上一阶段已经确认，掉线链路是：

```text
Profile / Replies
↓
X SPA navigation
↓
/thsottiaux/status/<tweet_id>
↓
旧 sourceForLocation() 无法识别 status 路由
↓
activeSource = null
↓
heartbeat / fallback scan / lifecycle 被 activeSource guard 跳过
↓
Backend 最终将 Monitor 判为 offline
```

这不是 Edge Tab discard/freeze、Content Script 整体失活、MV3 Service Worker 转发失败或 localhost Backend 接收故障：真实验证期间 Tab 均为 `complete`，`discarded=false`、`frozen=false`，Backend heartbeat 持续更新。

具体根因是 SPA status 路由的 monitor context classification 缺失。Profile 与 Replies 的修复前诊断都出现了 `next_source=null`，而修复后分别保持为 `profile_dom` 与 `with_replies`。

## 3. Code Change

### `extension/src/parser.ts`

- `sourceForLocation(pathname, previousSource)` 增加前序 source 参数。
- 当路径为 `/thsottiaux/status/<id>` 时，仅在 `previousSource` 为 `profile_dom` 或 `with_replies` 时继承该 source。
- 直接打开 Tibo status、其他用户 status、从 `search` 进入 status 均返回 `null`，不猜测 monitor 身份。

### `extension/src/content.ts`

- `inspectLocation()` 在重新分类前保存旧的 `activeSource`，并将其传给 `sourceForLocation()`。
- 保留原有诊断 instrumentation，包括 `LOCATION_CHANGED`、heartbeat timer、fallback scan、lifecycle、Observer、页面状态和 Tab 状态记录。

### `extension/src/parser.test.ts`

新增并覆盖：

- Profile → Tibo status 继续为 `profile_dom`；
- Replies → Tibo status 继续为 `with_replies`；
- status 返回 Profile / Replies 路由；
- 直接打开 status 不猜测 source；
- 其他用户 status 不继承 Profile；
- Search context 不继承为 Profile / Replies。

## 4. Unit Tests

- Extension Vitest：**12 passed**（`parser.test.ts` 11、`search.test.ts` 1）
- Backend pytest：**24 passed**
- TypeScript：`npx tsc --noEmit` 通过
- MV3：`npm run build` 通过，产物位于 `extension/dist`

## 5. Profile Real Test

测试 Tab：`973162150`

```text
00:39:52.184  /thsottiaux/
              → /thsottiaux/status/2093914342551101782
              previous_source=profile_dom
              next_source=profile_dom

01:14:36.203  Back 返回 /thsottiaux/
              previous_source=profile_dom
              next_source=profile_dom
```

status 停留窗口约 **2084 秒（34 分 44 秒）**，明显超过 3 个 heartbeat 周期。窗口内记录：

- `CONTENT_SCRIPT_HEARTBEAT_SENT`：73 次；
- `CONTENT_SCRIPT_HEARTBEAT_TIMER_TICK`：34 次；
- fallback scan started/completed：各 34 次；
- `CONTENT_SCRIPT_LIFECYCLE_TICK`：36 次；
- `TAB_STATE_SNAPSHOT`：35 次；
- 失败事件：0 条。

status 页面期间 `activeSource=profile_dom`，heartbeat、fallback scan、lifecycle 和 Backend 接收均持续；Back 后无需刷新或 reload 扩展即可恢复 Profile heartbeat。

## 6. Replies Real Test

测试 Tab：`973162737`

```text
01:37:53  /thsottiaux/with_replies
           → /thsottiaux/status/2093914587645247967
           previous_source=with_replies
           next_source=with_replies

01:42:59  Back 返回 /thsottiaux/with_replies
           previous_source=with_replies
           next_source=with_replies
```

status 停留窗口约 **306 秒（5 分 06 秒）**，覆盖超过 3 个 heartbeat 周期。窗口内记录：

- `CONTENT_SCRIPT_HEARTBEAT_SENT`：17 次；
- `CONTENT_SCRIPT_HEARTBEAT_TIMER_TICK`：6 次；
- fallback scan started/completed：各 6 次；
- `CONTENT_SCRIPT_LIFECYCLE_TICK`：11 次；
- 失败事件：0 条。

status 页面期间所有 fallback scan 的 `source=with_replies`，heartbeat 的 URL 为 status 页，且 Backend heartbeat 持续更新。Back 后 `activeSource` 恢复为 `with_replies`，无需刷新即可继续工作。

## 7. 回归与边界验证

已确认：

- `/thsottiaux/status/<id>` 只有在前序 context 为 Profile / Replies 时才继承 monitor；
- 直接打开 `/thsottiaux/status/<id>` 不会错误猜测 source；
- `/other_user/status/<id>` 不会继承 Tibo monitor context；
- `search → /thsottiaux/status/<id>` 不会错误继承为 Profile / Replies；
- Profile 和 Replies 的返回路由均可恢复正确 context；
- 诊断 instrumentation 保留，未引入自动 reload、reopen、watchdog 或 self-healing。

## 8. Final Health

最终查询时间约 2026-08-31 01:44（Asia/Shanghai）：

| Component | State | 关键状态 |
|---|---|---|
| Backend | `healthy` | `/api/health` 正常，累计 121 条 Tweet |
| Profile Monitor | `healthy` | URL `/thsottiaux/`，Tab `complete`，未 discarded/frozen |
| Replies Monitor | `healthy` | URL `/thsottiaux/with_replies`，Tab `complete`，未 discarded/frozen |
| Search Backfill | `healthy` | heartbeat 持续 |

## 9. 验收结论

**Profile / Replies SPA Route Fix：通过。**

共同根因已用最小修改修复，并通过自动化测试、Profile 真实 SPA 验证、Replies 真实 SPA 验证、Back 返回验证及最终四路 Health 检查。当前停止在本任务要求的范围内，不继续实施 Self-Healing、GitHub Mirror 或 Dashboard。
