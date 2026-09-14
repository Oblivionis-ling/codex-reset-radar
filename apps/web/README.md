# Codex Reset Radar V2 Web

Vite/TypeScript frontend for the local full-stack V2 runtime. It reads only `/api/v2/*` through the local Vite proxy. It does not access GitHub data branches, raw GitHub JSON, Pages runtime data, or credentials.

## Development

Run from the repository root:

```powershell
cd apps/web
npm ci
npm test
npm run typecheck
npm run build
npm run dev -- --host 127.0.0.1
```

See `docs/v2/local-development.md` for the full-stack workflow.
