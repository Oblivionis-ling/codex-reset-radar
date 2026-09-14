# Transitional Collector Adapter

This Manifest V3 extension is the legacy/transitional browser collector for V2 Alpha 1. It keeps the existing Profile, Replies, and Search collection path available while the future server collector remains out of scope.

It sends normalized public posts and ephemeral health/diagnostic messages only to the local Backend at `http://127.0.0.1:8787`. The V2 Backend does not persist routine heartbeat or browser lifecycle spam.

## Build

Run from the repository root:

```powershell
cd apps/collector-extension
npm ci
npm test
npm run typecheck
npm run build
```

Load `apps/collector-extension/dist` as an unpacked extension. It does not read browser cookies or use an X API credential.
