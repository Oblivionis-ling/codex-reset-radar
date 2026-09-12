import { defineConfig } from "vite";

const manifest = {
  manifest_version: 3,
  name: "Codex Reset Radar Transitional Collector",
  version: "0.2.0",
  version_name: "0.1.0-alpha.1",
  description: "Legacy browser collector adapter for the local Codex Reset Radar V2 Backend.",
  permissions: ["alarms", "storage", "tabs", "scripting"],
  host_permissions: ["https://x.com/*", "https://twitter.com/*", "http://127.0.0.1:8787/*", "http://localhost:8787/*"],
  background: { service_worker: "background.js", type: "module" },
  content_scripts: [
    {
      matches: ["https://x.com/thsottiaux", "https://x.com/thsottiaux/*", "https://twitter.com/thsottiaux", "https://twitter.com/thsottiaux/*", "https://x.com/search*", "https://twitter.com/search*"],
      js: ["content.js"],
      run_at: "document_idle"
    }
  ],
  action: { default_title: "Codex Reset Radar" }
};

export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      input: {
        background: "src/background.ts",
        content: "src/content.ts"
      },
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "chunks/[name].js",
        assetFileNames: "assets/[name][extname]"
      }
    }
  },
  plugins: [
    {
      name: "emit-manifest",
      generateBundle() {
        this.emitFile({ type: "asset", fileName: "manifest.json", source: JSON.stringify(manifest, null, 2) });
      }
    }
  ]
});
