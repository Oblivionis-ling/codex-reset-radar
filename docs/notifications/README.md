# Notification channels

Status date: 2026-09-19. This is the current engineering and contract reference for notification
preparation. User actions are in [testing-guide.md](testing-guide.md).

## Safety boundary

The notification package is not connected to Reset events, Judge runs, Backend startup or any
scheduler. `prepare`, `status`, `check`, `preview` and `selftest` cannot reach provider or SMTP
networks. Live testing requires all three conditions:

1. one named channel is selected;
2. the command includes `--live`;
3. the user types the exact interactive confirmation phrase.

Secrets are read only from the ignored Backend-local `.env`. Token-bearing URL paths and query values
are redacted. No credential is returned to the Web or stored in the source tree.

## Architecture

```text
test-notifications.bat
  -> one message model and one persistent dedup ledger
  -> one bounded-retry HTTP transport
       -> thin PushPlus / ServerChan / IYUU / WPush / WxPusher / ShowDoc adapters
  -> independent verified-TLS SMTP adapter
```

The adapters report `request_accepted`, provider state and `user_observation_required` separately.
HTTP 200 with a failed business code is a failure. `ACCEPTED` or `PENDING` never means that a phone
displayed the notification.

The local delivery ledger is `runtime/notifications/notification-deliveries.db`. It is separate from
the product database and exists only after an explicit live attempt or local result inspection.

## Current channel contracts

| Channel | Request | Result handling | Preparation state |
| --- | --- | --- | --- |
| PushPlus WeChat | HTTPS JSON `POST /send`, `channel=wechat` | `code=200` is asynchronous acceptance; message serial is retained, public polling contract not verified | Implemented, offline tested |
| PushPlus ClawBot | Same adapter, `channel=clawbot` | Same asynchronous semantics; binding and periodic interaction are provider requirements | Implemented, offline tested, conditional account setup |
| Server酱 Turbo | HTTPS form POST to tokenized `.send` URL | `code=0` means API accepted; no per-message query used | Implemented, offline tested |
| IYUU | HTTPS form POST to tokenized `.send` URL | `errcode=0` means API accepted; no per-message query used | Implemented, offline tested |
| WPush WeChat / ClawBot | HTTPS form `POST /api/v1/send` | `code=0`; message ID is queried through `/api/v1/query`, status 0/1/2 = pending/success/failure | Implemented, offline tested |
| WxPusher | HTTPS JSON `POST /api/send/message` | business `code=1000`; `sendRecordId` queried through `/api/send/query/status` | Existing concept consolidated into V2, offline tested |
| ShowDoc push | HTTPS form POST to dedicated token URL | `error_code=0` means API accepted; no per-message query used | Contract verified from official service client, implemented, offline tested |
| SMTP email | Python SMTP with STARTTLS or implicit TLS and default certificate verification | SMTP acceptance is recorded; inbox receipt remains a user observation | Implemented, offline tested |

ClawBot is a channel parameter of PushPlus or WPush, not a copied transport. WPush platform email is
not used as the fallback; fallback email goes directly from the user's authorised mailbox over SMTP.

## Official evidence used

- PushPlus message API and async semantics: <https://www.pushplus.plus/doc/guide/api.html>
- PushPlus HTTPS support: <https://www.pushplus.plus/doc/help/https.html>
- PushPlus ClawBot requirements: <https://www.pushplus.plus/doc/channel/clawbot.html>
- Server酱 SendKey and response contract: <https://sct.ftqq.com/docs/getting-started/sendkey/>
- Server酱 limits/troubleshooting: <https://sct.ftqq.com/docs/getting-started/faq/>
- IYUU POST contract: <https://iyuu.cn/article/2>
- WPush API reference: <https://wpush.cn/docs>
- WxPusher OpenAPI: <https://wxpusher.zjiecode.com/docs/openapi.yaml>
- ShowDoc push service: <https://push.showdoc.com.cn/>

Provider entitlement, quotas, pricing and binding rules can change; the provider's current console is
authoritative at the time of the manual test.

## Configuration

Copy only the fields needed for the selected test into `.env`:

```dotenv
PUSHPLUS_TOKEN=
SERVERCHAN_SENDKEY=
IYUU_TOKEN=
WPUSH_API_KEY=
WXPUSHER_APP_TOKEN=
WXPUSHER_UID=
SHOWDOC_PUSH_TOKEN=

CRR_SMTP_HOST=
CRR_SMTP_PORT=587
CRR_SMTP_USERNAME=
CRR_SMTP_PASSWORD=
CRR_SMTP_FROM=
CRR_SMTP_TO=
CRR_SMTP_SECURITY=starttls
```

`CRR_SMTP_SECURITY` accepts only `starttls` or `ssl`; plaintext downgrade is rejected. Do not put a
secret on a command line.

## Developer verification

```powershell
.\test-notifications.bat check
.\test-notifications.bat preview
.\test-notifications.bat selftest
backend\.venv\Scripts\python.exe -m pytest apps\backend\tests\test_notifications.py -q
```

Offline fixtures use in-memory transports. Their only success label is `OFFLINE_PASS`, never
`DELIVERED`.
