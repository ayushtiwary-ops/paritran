import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// Second Vite entry: the hosted interactive solution served at /paritran/app/
// (SPEC_HOSTED_APP.md). Build input is replay.html; output goes to ../docs/app,
// which GitHub Pages already serves. emptyOutDir is false so the committed
// vendor/, py/, and replay/ trees under docs/app survive the build; Vite writes
// only the HTML entry and assets/. The production frontend build (vite.config.ts)
// and its config are not touched.
export default defineConfig({
  plugins: [react()],
  base: "/paritran/app/",
  worker: { format: "es" },
  build: {
    target: "es2022",
    outDir: fileURLToPath(new URL("../docs/app", import.meta.url)),
    emptyOutDir: false,
    assetsDir: "assets",
    rollupOptions: {
      input: fileURLToPath(new URL("./replay.html", import.meta.url)),
    },
  },
});
