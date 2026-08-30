import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { defineConfig, type Plugin } from "vite";

const dashboardDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(dashboardDir, "..");
const publicDataDir = path.join(projectRoot, "public-data");
const publicDataFiles = ["index.json", "tweets.json", "radar.json", "health.json"] as const;

function publicDataPlugin(): Plugin {
  return {
    name: "codex-reset-radar-public-data",
    configureServer(server) {
      server.middlewares.use("/public-data", (request, response, next) => {
        const pathname = request.url?.split("?", 1)[0] ?? "";
        const filename = pathname.replace(/^\/public-data\//, "");
        if (!publicDataFiles.includes(filename as (typeof publicDataFiles)[number])) {
          next();
          return;
        }
        try {
          response.statusCode = 200;
          response.setHeader("Content-Type", "application/json; charset=utf-8");
          response.end(readFileSync(path.join(publicDataDir, filename)));
        } catch {
          next();
        }
      });
    },
    generateBundle() {
      for (const filename of publicDataFiles) {
        this.emitFile({
          type: "asset",
          fileName: `public-data/${filename}`,
          source: readFileSync(path.join(publicDataDir, filename), "utf-8")
        });
      }
    }
  };
}

export default defineConfig({
  base: "./",
  plugins: [publicDataPlugin()],
  build: {
    outDir: "dist",
    emptyOutDir: true
  }
});
