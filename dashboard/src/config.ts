const LIVE_DATA_BASE_URL = "https://raw.githubusercontent.com/Oblivionis-ling/codex-reset-radar/refs/heads/data/";

// Vite serves the repository's sample snapshot during local development. The
// production build reads the independent data branch so data updates do not
// require another Pages deployment.
export const DATA_BASE_URL = import.meta.env.DEV ? "/public-data/" : LIVE_DATA_BASE_URL;
