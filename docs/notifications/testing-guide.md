# 通知渠道人工测试指南

## 先看这一屏

已经准备好：PushPlus、Server酱 Turbo、IYUU、WPush、WxPusher、ShowDoc 和独立 SMTP 邮件的
共用测试入口、消息预览、离线自测、失败处理和本地结果记录。

建议顺序：**Server酱 Turbo → PushPlus 微信公众号 → WPush 微信公众号 → IYUU → WxPusher／ShowDoc
备选 → 独立 SMTP → 有需要时再测 ClawBot**。

你只需要：在对应官网扫码/关注或登录，复制该渠道自己的凭据到根目录 `.env`，然后双击：

```text
D:\work\20260828-CodexResetRadar\test-notifications.bat
```

目前真实微信发送 **0**、真实邮件发送 **0**、账号绑定变化 **0**。不要把 Token、SendKey、
API Key 或邮箱授权码贴回聊天。

## 统一入口怎么用

双击 `test-notifications.bat` 只显示菜单，不发送。菜单中的“状态”“配置检查”“预览”和
“离线自测”都不会访问真实发送接口。

也可以从项目根目录运行：

```powershell
.\test-notifications.bat status
.\test-notifications.bat check
.\test-notifications.bat preview
.\test-notifications.bat selftest
```

真实测试必须选一个渠道，并进行二次确认：

```powershell
.\test-notifications.bat send --channel serverchan_wechat --live
```

程序会再次要求输入 `SEND serverchan_wechat`。一次只测一个渠道。所有测试消息的标题和正文
开头都是“测试，非真实 Reset 预警”。程序的 `ACCEPTED`／`PENDING` 只代表接口状态，手机
是否收到仍由你记录。

## PushPlus 微信公众号

| 项目 | 操作 |
| --- | --- |
| 去哪里 | <https://www.pushplus.plus/>；接口说明见 <https://www.pushplus.plus/doc/guide/api.html> |
| 做什么 | 按官网当前流程登录并关注/激活 PushPlus 微信公众号渠道 |
| 复制什么 | 用户 Token 或仅供本次单目标测试的消息 Token |
| 填哪里 | `.env` 的 `PUSHPLUS_TOKEN=` |
| 怎么测试 | 统一入口选 `pushplus_wechat` |
| 手机看哪里 | PushPlus 对应的微信公众号会话及系统锁屏通知 |
| 如何判断 | 微信内收到、标题明确为测试、正文可读、链接可打开，并记录延迟 |
| 失败怎么办 | 先看返回业务码，再检查 Token、渠道激活和当前额度；涉及实名/会员时可跳过 |

## PushPlus ClawBot（条件性渠道）

| 项目 | 操作 |
| --- | --- |
| 去哪里 | <https://www.pushplus.plus/doc/channel/clawbot.html> |
| 做什么 | 官方流程为“个人中心 → 渠道配置 → 微信ClawBot → 立即绑定”，扫码后主动发起一次对话并确认已激活 |
| 复制什么 | 与 PushPlus 共用的 Token |
| 填哪里 | `.env` 的 `PUSHPLUS_TOKEN=` |
| 怎么测试 | 统一入口选 `pushplus_clawbot` |
| 手机看哪里 | 微信 ClawBot 对话，不是普通服务号模板消息 |
| 如何判断 | 对话内收到文字、锁屏提示和延迟均可接受 |
| 失败怎么办 | 官方当前要求绑定后先主动对话，并有周期性再次互动限制；一个微信号已有其他 ClawBot 绑定时先不要替换，跳过即可 |

## Server酱 Turbo

| 项目 | 操作 |
| --- | --- |
| 去哪里 | <https://sct.ftqq.com/>；SendKey 指南见 <https://sct.ftqq.com/docs/getting-started/sendkey/> |
| 做什么 | 微信扫码登录 Turbo；进入官网当前的 `SendKey` 页面并复制 SCT 开头的密钥 |
| 复制什么 | Turbo SendKey（SCT 开头；不要用 Server酱³ 的 sctp Key） |
| 填哪里 | `.env` 的 `SERVERCHAN_SENDKEY=` |
| 怎么测试 | 统一入口选 `serverchan_wechat` |
| 手机看哪里 | 你在 Server酱中启用的微信落点；不要误看 Server酱³ 独立 App |
| 如何判断 | 微信内收到、锁屏提示、Markdown 正文可读、延迟可接受 |
| 失败怎么办 | 检查返回 `code`、当天额度、频率限制和微信关注状态；额度/订阅不合适可跳过 |

## IYUU

| 项目 | 操作 |
| --- | --- |
| 去哪里 | <https://iyuu.cn/>；POST 文档见 <https://iyuu.cn/article/2> |
| 做什么 | 按官网当前登录流程取得页面显示的 IYUU 令牌，并完成其微信接收要求 |
| 复制什么 | IYUU 令牌（不复制整条带正文的测试 URL） |
| 填哪里 | `.env` 的 `IYUU_TOKEN=` |
| 怎么测试 | 统一入口选 `iyuu_wechat` |
| 手机看哪里 | 爱语飞飞对应的微信会话 |
| 如何判断 | 微信内与锁屏均观察，正文和延迟可接受 |
| 失败怎么办 | `errcode` 非 0 时按 `errmsg` 排查 Token/关注状态；官网条件不适合时跳过 |

## WPush 微信公众号

| 项目 | 操作 |
| --- | --- |
| 去哪里 | <https://wpush.cn/>；API 参考见 <https://wpush.cn/docs> |
| 做什么 | 登录后在“渠道”中配置微信公众号，在“设置”中查看/复制 API Key |
| 复制什么 | `WPUSH_` 开头的 API Key |
| 填哪里 | `.env` 的 `WPUSH_API_KEY=` |
| 怎么测试 | 统一入口选 `wpush_wechat` |
| 手机看哪里 | WPush 配置的微信公众号会话 |
| 如何判断 | 微信内、锁屏、正文、链接与延迟；程序会额外查询消息状态 |
| 失败怎么办 | 检查业务 `code`、渠道绑定、当前体验额度；若需购买或额外资格可跳过 |

WPush 的 ClawBot 使用同一个 API Key，完成 WPush 里的 ClawBot 绑定后选
`wpush_clawbot`；它复用同一发送实现，不会产生第二套配置。

## WxPusher（备选）

| 项目 | 操作 |
| --- | --- |
| 去哪里 | <https://wxpusher.zjiecode.com/admin/>；OpenAPI 见 <https://wxpusher.zjiecode.com/docs/openapi.yaml> |
| 做什么 | 使用标准应用时创建/选择应用，让自己的接收端订阅并取得 UID；具体接收端以账号中实际配置为准 |
| 复制什么 | App Token 与自己的 UID |
| 填哪里 | `.env` 的 `WXPUSHER_APP_TOKEN=`、`WXPUSHER_UID=` |
| 怎么测试 | 统一入口选 `wxpusher` |
| 手机看哪里 | 你实际绑定的 WxPusher 客户端或 ClawBot；它不保证是普通微信公众号落点 |
| 如何判断 | 对应接收端收到，正文可读、延迟可接受；程序会查询 `sendRecordId` |
| 失败怎么办 | 检查业务 `code=1000`、UID/App Token 配对和接收端订阅状态 |

## ShowDoc 推送（备选）

| 项目 | 操作 |
| --- | --- |
| 去哪里 | <https://push.showdoc.com.cn/> 或 <https://www.showdoc.com.cn/push> |
| 做什么 | 按页面扫码登录并关注公众号，登录后复制页面生成的专属推送 URL |
| 复制什么 | 专属 URL 最后 `/push/` 后面的 Token；不要把整条 URL贴到日志或聊天 |
| 填哪里 | `.env` 的 `SHOWDOC_PUSH_TOKEN=` |
| 怎么测试 | 统一入口选 `showdoc_wechat` |
| 手机看哪里 | ShowDoc 推送服务对应的微信公众号会话 |
| 如何判断 | 微信内收到、锁屏提示、正文和延迟可接受 |
| 失败怎么办 | 检查 `error_code`、专属 Token 和公众号关注状态；无状态查询时以手机观察为准 |

## 独立 SMTP 邮件

| 项目 | 操作 |
| --- | --- |
| 去哪里 | 你选择的发件邮箱官方“SMTP/客户端授权”说明页 |
| 做什么 | 确认 SMTP 主机、端口和 TLS 模式，按邮箱官方流程创建客户端授权码；不要使用网页登录密码，除非官方明确要求 |
| 复制什么 | SMTP 用户名和授权码；另准备发件人与收件邮箱 |
| 填哪里 | `.env` 的 `CRR_SMTP_HOST/PORT/USERNAME/PASSWORD/FROM/TO/SECURITY` |
| 怎么测试 | 统一入口选 `smtp_email`；之后可在微信渠道测试时明确选择邮件兜底 |
| 手机看哪里 | 收件邮箱 Inbox 和 Spam；锁屏取决于你的邮件 App 设置 |
| 如何判断 | 主题明确为测试、中文正文与本地链接可读、延迟可接受 |
| 失败怎么办 | 程序会区分认证失败、拒收、TLS、超时；不支持关闭证书校验或退回明文认证 |

直接邮件通过后，可选择菜单 7，或运行下列命令。它不会访问微信接口，只在本地模拟微信明确
失败，然后在你输入 `SEND smtp_fallback` 后真实发送一封保底测试邮件：

```powershell
.\test-notifications.bat fallback-test --reason failure --live
```

将 `failure` 改成 `unknown` 可验证“微信结果未确认”文案。同一运行标识的兜底只会排队一次，
邮件失败不会递归生成另一封失败通知。

## 人工观察记录

每个可用微信渠道先测前台一条，再根据额度测后台/锁屏一条；邮件测直接一封，再测一次明确
启用的“微信失败/未确认后转邮件”。两次即时测试不等于长期稳定性验证。

| 渠道 | 微信内收到 | 锁屏提示 | 正文可读 | 大致延迟 | 使用是否麻烦 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |

测试完成后不要把凭据或完整 Token 截图发回。只需提供上表的手机观察和程序显示的脱敏状态/错误码。
