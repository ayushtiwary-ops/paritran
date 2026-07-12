import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-server proxy targets the published api port on the host (8090 per SPEC
// section 2). In the container path, nginx (infra/docker/nginx.conf) does the
// equivalent proxying to http://api:8000, so the app code always calls
// same-origin /api and /health and never hardcodes a backend host.
//
// VITE_PROXY_TARGET overrides the target without touching source: the demo
// e2e (SPEC 14) points it at a local uvicorn running the edited backend so
// the /api/demo/* endpoints exist even when the published container predates
// them. Unset, the default 8090 behavior is unchanged.
const proxyTarget = process.env.VITE_PROXY_TARGET ?? "http://localhost:8090";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": proxyTarget,
      "/health": proxyTarget,
    },
  },
});
