# Codex Reset Radar Dashboard

This is a static TypeScript/Vite dashboard. It reads only the repository's public-data JSON files, including `resets.json`. It never calls the local Backend and contains no credentials, OAuth flow, API key, or server-side code.

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

The dashboard defaults to Chinese on first visit. Use the top-right language button to switch to English; the choice is kept locally in the browser. Tweet cards show a local Backend translation when available and always preserve the English source text.

Navigation uses hash routes (`#/`, `#/tweets`, `#/resets`) so direct GitHub Pages visits do not require server-side rewrites.
