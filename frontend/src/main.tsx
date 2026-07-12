import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Self-hosted IBM Plex families (SPEC 10.1). Vite bundles the woff2 files
// into the build output; nothing is fetched from a CDN.
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-serif/400.css";
import "@fontsource/ibm-plex-serif/600.css";

import "./design/tokens.css";
import "./design/app.css";
import App from "./App";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 401s are handled inside apiFetch (one refresh + retry); other
      // errors surface to the screens, which render them honestly.
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("index.html is missing the #root element");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
