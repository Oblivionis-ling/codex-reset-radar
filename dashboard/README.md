# Codex Reset Radar Dashboard

This is a static TypeScript/Vite dashboard. It reads only the repository's `public-data/index.json`, `tweets.json`, `radar.json`, and `health.json` files. It never calls the local Backend and contains no credentials, OAuth flow, API key, or server-side code.

## Local development

From the repository root:

```powershell
cd dashboard
npm install
npm test
npm run build
npm run dev
```

The Vite plugin serves the root `public-data/` directory at `/public-data/` during development and emits the same files into the production artifact. `base: "./"` and URL resolution against `document.baseURI` keep the app working at `/codex-reset-radar/` on GitHub Pages.
