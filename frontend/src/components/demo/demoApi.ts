/**
 * Demo-mode REST helpers (SPEC 9.1, 14). Every field mirrors a backend
 * response model; no number is invented here (truth rule 1).
 */

import { apiFetch } from "../../lib/api";
import type { DemoPlanted } from "../../lib/sse";

export interface DemoStarted {
  demo_id: string;
  run_id: string;
  seed: number;
  generator: string;
  demo_stream_url: string;
  run_stream_url: string;
}

/** POST /api/demo/start (supervisor): launch the paced narrative + run. */
export function startDemo(): Promise<DemoStarted> {
  return apiFetch<DemoStarted>("/api/demo/start", { method: "POST" });
}

/**
 * POST /api/demo/plant-fabrication (supervisor): push one planted,
 * labelled claim through the live F9 gate against corpus v2. The response
 * is the real verdict; a correct gate returns verdict WITHHELD / blocked.
 */
export function plantFabrication(): Promise<DemoPlanted> {
  return apiFetch<DemoPlanted>("/api/demo/plant-fabrication", {
    method: "POST",
  });
}
