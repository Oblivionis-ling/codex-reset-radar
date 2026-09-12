# Codex Reset Radar extension

This is a Chrome/Edge Manifest V3 extension built with Vite and TypeScript.

## Build

```powershell
npm install
npm test
npm run build
```

Load the generated `dist` folder as an unpacked extension. The content script is intentionally limited to Tibo's Profile, `with_replies`, and X Search pages. It does not read cookies or call an X API.

The service worker posts normalized Tweets and heartbeats to `http://127.0.0.1:8787`. When the backend is unavailable, raw Tweet payloads are kept in `chrome.storage.local` and retried.

