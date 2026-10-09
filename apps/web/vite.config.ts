import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { defineConfig } from "vite";

const webDir = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(webDir, "../..");
const appVersion = readFileSync(path.join(repositoryRoot, "VERSION"), "utf-8").trim();
const backendTarget = process.env.CRR_WEB_BACKEND_URL?.trim() || "http://127.0.0.1:8787";
const backendUrl = new URL(backendTarget);
if (backendUrl.protocol !== "http:"
  || !["127.0.0.1", "localhost", "[::1]"].includes(backendUrl.hostname)
  || backendUrl.pathname !== "/"
  || backendUrl.search
  || backendUrl.hash) {
  throw new Error("CRR_WEB_BACKEND_URL must be an HTTP loopback URL for an isolated local Backend.");
}

export default defineConfig({
  base: "/",
  define: { __APP_VERSION__: JSON.stringify(appVersion) },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: backendTarget, changeOrigin: false }
    }
  },
  build: { outDir: "dist", emptyOutDir: true }
});
