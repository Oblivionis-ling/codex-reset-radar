# Phase B.5 类别变化清单

比较口径：校准前最近一轮 `tibo-classifier-v1` Final vs 校准后最近一轮 `tibo-classifier-v2-calibrated` Final。只列类别发生变化的唯一 Tweet；同一 Tweet 的其他审计历史不重复列出。

## 1. `2093014447833116908`

- Text：Never slept better and feeling reseted. Brand new me and brand new usage for all ChatGPT Work and Codex users. Regaining my youth one button press at a time. Happy Thursday
- Old Final：`codex_related`（Rule fallback）
- New Final：`reset_confirmed`，confidence `0.85`，urgency `now`，explicitness `explicit`
- Reason for Change：新增 reset 词形 `reseted`，并识别“brand new usage + button press”恢复 usage 的 Reset 事件语义；DeepSeek v2 确认已生效。

## 2. `2093551005711679557`

- Text：There is a place and a time for resets. Soon, but not today
- Old Final：`unrelated`
- New Final：`reset_hint`，confidence `0.72`，urgency `within_3d`，explicitness `implicit`
- Reason for Change：扩展 `resets` 词形和 reset+时间语义；区分“soon, but not today”的 future hint 与 denial，DeepSeek v2 确认为隐含提示。

## 3. 其他记录

其余 105 条 Tweet 的类别在校准前后保持不变。C–G 样本在第一轮 v1 AI backfill 时已经从旧 fallback 得到正确 Reset 类别；本次 v2 重新确认了它们的 Rule 边界和审计结果。
