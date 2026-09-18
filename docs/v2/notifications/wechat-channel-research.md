# WeChat Notification Channel Research

Checked on 2026-09-17. This phase performed documentation research only: no account registration, binding, migration, purchase, credential access, API call, or real message send was performed.

## Decision summary

**There is not yet a fully verified route that satisfies every requirement.** The strongest long-term candidate is a certified WeChat Service Account using an approved service notification/template category, because it reaches ordinary WeChat users and has platform-native delivery/receipt semantics. Its blockers are material: entity/certification eligibility, template/category approval for Reset alerts, public HTTPS callbacks, and an actual phone delivery test.

For current personal use, **PushPlus one-to-one** is the easiest new candidate to test after a product decision; its documented real-name quota covers two alerts per day, while membership (`CNY 10/month` in the checked vendor page) improves quota and WeChat content display. **Server酱 Turbo** is a second personal candidate: its official landing page advertises five free messages per day, enough for the two-message sample, but the checked public material does not establish a centralized public subscription model.

**WxPusher remains the designated backup.** Its standard API has good multi-user mechanics, but its current documentation says the primary direction is independent clients. Its WeChat ClawBot/iLink path allows 10 messages during a 24-hour activation and requires the user to reply again when the window/count is exhausted, which conflicts with the requirement not to depend on daily manual activation.

## Official platform routes

### Certified WeChat Service Account

Official documentation: <https://developers.weixin.qq.com/doc/offiaccount/Message_Management/Template_Message_Interface.html>

- Template messages are for important service notifications, not advertising or potentially harassing content.
- Only certified Service Accounts may apply for template-message permission.
- The category and template must fit the account's approved service category.
- The documented default daily account limit is 100,000 calls, with actual account limits shown in the MP console.
- A completion event is pushed to the configured server and can report platform delivery success; that is stronger than treating the initial API response as receipt.
- The same page says Service Account subscription notifications are in grey testing while template messages remain usable.

Fit: best ordinary-WeChat long-term candidate **if** a suitable service category/template is approved. A general “Codex Reset forecast” may not qualify; no attempt should be made to disguise it as an unrelated transactional template.

Current local feasibility: not directly usable. It requires an eligible/certified account, approved template and public HTTPS callback. `127.0.0.1` cannot be the callback or phone detail link.

### Mini Program subscription messages

Official documentation:

- <https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/subscribe-message.html>
- <https://developers.weixin.qq.com/miniprogram/dev/api/open-api/subscribe-message/wx.requestSubscribeMessage.html>

The user must invoke the subscription UI from a click or payment callback. One-time and permanent template IDs cannot be mixed in one request. The account/template must actually have the relevant message capability; this research did not verify that Codex alerts can obtain a permanent template. Users can reject or later change subscription status. The guide documents a very high server-side daily ceiling (10 million without payment capability, 30 million with it), so platform throughput is not the likely bottleneck; durable authorization and category eligibility are.

Fit: potentially good opt-in UX, but one-time authorization is a poor match for irregular alerts, and permanent-template eligibility remains unverified. It also requires a Mini Program plus public backend/callback work, so it is not a local-only solution.

### Official Account customer-service messages

Official documentation: <https://developers.weixin.qq.com/doc/offiaccount/Message_Management/Service_Center_messages.html>

This route is tied to user interaction/customer-service messaging rather than durable event subscriptions. The checked page documents receiving user messages and API responses but did not expose enough current window rules to prove it can send indefinite proactive Reset alerts. It is therefore not selected.

### WeCom application messages

Official documentation: <https://developer.work.weixin.qq.com/document/path/90236>

- A request can name up to 1,000 member IDs; recipients must be within the application's visible/licensed scope.
- The page documents an application daily cap of `account member limit × 200 person-times`; sending to 1,000 people counts as 1,000 person-times.
- Per-member limits are 30/minute and 1,000/hour.
- Text content is limited to 2,048 bytes and can contain links.

Fit: strong for the operator's own enterprise members, not a public subscription channel for arbitrary ordinary-WeChat users. Enterprise member application messages, external contacts, and group robots are different products and must not be conflated.

### WeChat ClawBot / iLink

No independent public WeChat developer document proving a generally available, stable notification API was located in this research. Two provider documents describe a WeChat ClawBot/iLink channel:

- PushPlus: <https://www.pushplus.plus/doc/channel/clawbot.html>
- WxPusher: <https://wxpusher.zjiecode.com/docs/README.md>

Both describe active-message limits and reactivation. PushPlus states that binding requires a scan and an initial conversation, then a new conversation after every 10 downstream messages or every 24 hours. WxPusher states 10 messages in a 24-hour activation and a user reply to reactivate. These are provider-supported claims, not independently validated WeChat platform terms in this phase.

Fit: experimental personal/backup route only. The recurring activation requirement directly conflicts with the product requirement.

## Third-party routes

| Route | Ordinary WeChat location | Personal | Central multi-user | Open-source self-host | Subscription / cancellation | Receipt strength | Important limits and cost evidence | Result |
|---|---|---:|---:|---:|---|---|---|---|
| PushPlus WeChat channel | PushPlus public-account/service notification surface; exact phone banner behavior not tested | Yes | Yes: topics and friend tokens | Each deployment can use its own token; service itself is vendor-hosted | Topic QR/link join; user can leave, owner can remove | API is asynchronous; vendor says query final message result | Real-name: 200 WeChat-channel requests/day; member: 2,000/day; member price CNY 10/month. Real-name WeChat display may show only title; member shows more content | Personal candidate; conditional multi-user candidate |
| PushPlus ClawBot | WeChat ClawBot conversation | Yes | Provider says one-to-one/topic/friend work | Per-deployment vendor token | Scan/bind plus active conversation | Provider-level result only | 10 downstream messages or 24 hours before user conversation is needed again | Not suitable as main route |
| Server酱 Turbo | Vendor's WeChat route; exact inbox/banner behavior not tested | Yes | Public-subscriber fan-out not established | Per-deployment SendKey is plausible | User binds own account; centralized unsubscribe model not established | API/provider response; phone receipt not tested | Official landing page advertises 5 free messages/day; paid capacity and per-recipient accounting were not verified | Personal alternative only |
| WxPusher standard | Current docs prioritize WxPusher apps; optional WeChat iLink channel | Yes | Yes: UID lists or topics | Each deployment can own an appToken/SPT; service remains vendor-hosted | App/topic QR/link, UID management, delete/block APIs | Per UID/topic task plus queryable send record; not proof of phone banner | Free docs; max 2,000 UIDs or 5 topics/request, ~2 QPS. iLink separately limits 10/24h activation | Fixed backup |
| WeCom app | WeCom member app message | Yes for own enterprise | Yes for members, not arbitrary public subscribers | Each deployment can use its own enterprise app | Admin/member lifecycle, not public opt-in | WeCom API result and invalid-user lists | Up to 1,000 member IDs/request; member/license scope applies | Internal-team option only |

PushPlus evidence:

- One-to-one, topic and friend models: <https://www.pushplus.plus/doc/function/one.html>, <https://www.pushplus.plus/doc/function/more.html>, <https://www.pushplus.plus/doc/function/friend.html>
- Quotas: <https://www.pushplus.plus/doc/guide/use.html>
- Membership: <https://www.pushplus.plus/doc/function/vip.html>

WxPusher evidence: <https://wxpusher.zjiecode.com/docs/README.md>. Standard apps support UID and topic sends, callback/user management, a maximum of 2,000 UIDs in one request, and queryable send records. SPT is simpler but limited to 10 recipients and cannot manage users like a standard app.

## Capacity example: two events per user per day

| Route | 1 user | 100 subscribers | 1,000 subscribers | Cost conclusion from checked evidence |
|---|---:|---:|---:|---|
| Service Account template | 2 deliveries / about 2 API calls | 200 / about 200 | 2,000 / about 2,000 | Message fee not stated in checked official page; all are below 100,000/day. Account/certification cost not quantified here |
| Mini Program subscription | 2 / 2 | 200 / 200 | 2,000 / 2,000 | Message fee not stated; far below documented server ceiling, but each user's authorization must be valid |
| WeCom application | 2 / 2 | 200 deliveries / potentially 2 batched calls | 2,000 deliveries / potentially 2 batched calls | No per-message fee established; membership/license qualification is the constraint |
| PushPlus topic | 2 / 2 | 200 deliveries / 2 topic calls | 2,000 deliveries / 2 calls if topic capacity is provisioned | Verified account's documented group cap is 100; member cap 500/group and 50 groups, so 1,000 requires member capacity (documented CNY 10/month) and at least two groups |
| WxPusher topic or UID list | 2 / 2 | 200 deliveries / 2 calls | 2,000 deliveries / 2 calls (1,000 < 2,000 UID/request) | Service documentation calls it free; downstream iLink activation limits remain per user |
| Server酱 personal | 2 / 2 | Unknown centralized fan-out | Unknown | Five free calls/day supports personal two-event use only; multi-user accounting/cost was not verified |

“Two topic calls” does not mean only two user deliveries. The table keeps event count, API calls, and delivered-recipient count separate. Provider/API acceptance also does not prove that iOS/Android displayed a system notification.

## Recommended next validation (not executed)

1. Confirm whether the operator has an eligible certified Service Account and whether a compliant service template exists for alerting about third-party product usage resets.
2. If not, test PushPlus one-to-one on one phone: ordinary-WeChat location, visible正文, background/system notification, asynchronous result query, and unsubscribe.
3. Keep the existing WxPusher integration disabled as the default but available as fallback; do not remove it.
4. Before any multi-user implementation, define subscriber consent, encrypted token/UID storage, removal/opt-out, delivery receipts, rate limiting and a public details URL. Never link a phone message to `127.0.0.1`.

## Unverified items

- Service Account category/template approval for this exact product content.
- Permanent Mini Program subscription-template eligibility for this category.
- Actual phone notification presentation for every third-party channel.
- Server酱 paid pricing and public multi-user subscription mechanics.
- A first-party, stable WeChat ClawBot/iLink developer contract independent of provider documentation.
- Whether any two providers share the same downstream WeChat failure domain in the exact configured mode.
