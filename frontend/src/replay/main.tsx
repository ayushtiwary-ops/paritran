import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Self-hosted IBM Plex families (SPEC 10.1). Vite bundles the woff2 files into
// docs/app/assets; nothing is fetched from a CDN (zero-egress, acceptance A10).
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-serif/latin-700.css";

import "../design/tokens.css";
import "./replay.css";
import { ReplayApp } from "./ReplayApp";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("replay.html is missing the #root element");
}

createRoot(rootElement).render(
  <StrictMode>
    <ReplayApp />
  </StrictMode>,
);
