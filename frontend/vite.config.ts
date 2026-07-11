import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-server proxy targets the published api port on the host (8090 per SPEC
// section 2). In the container path, nginx (infra/docker/nginx.conf) does the
// equivalent proxying to http://api:8000, so the app code always calls
// same-origin /api and /health and never hardcodes a backend host.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8090",
      "/health": "http://localhost:8090",
    },
  },
});
