/**
 * Security posture endpoint helper and response types (SPEC 9.1, 11).
 * Each interface mirrors backend/paritran/api/routers/security.py field
 * for field; nothing is derived or defaulted here (truth rule 1).
 */

import { apiFetch } from "../../lib/api";

export interface ScannerSummary {
  status: string;
  critical: number | null;
  high: number | null;
  medium: number | null;
  low: number | null;
  unknown: number | null;
  findings_total: number | null;
  ran_at: string | null;
  note: string | null;
  error_detail: string | null;
}

export interface OutboundEndpoint {
  name: string;
  endpoint: string;
  purpose: string;
}

export interface EgressSelfTest {
  attempted: boolean;
  result: string;
  target: string;
  timeout_seconds: number;
  checked_at: string;
  detail: string;
}

export interface SecurityPosture {
  summary_available: boolean;
  summary_generated_at: string | null;
  last_scan_at: string | null;
  scans: Record<string, ScannerSummary>;
  scans_dir: string;
  scans_source: string;
  outbound_endpoints: OutboundEndpoint[];
  egress: EgressSelfTest;
}

export function getPosture(): Promise<SecurityPosture> {
  return apiFetch<SecurityPosture>("/api/security/posture");
}
