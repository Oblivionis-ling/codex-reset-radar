import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { defineConfig } from "vite";

const webDir = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(webDir, "../..");
const appVersion = readFileSync(path.join(repositoryRoot, "VERSION"), "utf-8").trim();

export default defineConfig({
  base: "/",
  define: { __APP_VERSION__: JSON.stringify(appVersion) },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8787", changeOrigin: false }
    }
  },
  build: { outDir: "dist", emptyOutDir: true }
});
