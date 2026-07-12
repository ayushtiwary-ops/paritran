/**
 * Custody Ledger endpoint helpers and response types (SPEC 9.1, 8).
 * Each interface mirrors backend/paritran/api/routers/audit.py field
 * for field; nothing is derived or defaulted here (truth rule 1).
 */

import { apiFetch } from "../../lib/api";

export interface AuditRow {
  seq: number;
  ts: string;
  actor: string;
  action: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  hash: string;
}

export interface ChainPage {
  total: number;
  limit: number;
  offset: number;
  rows: AuditRow[];
}

export interface VerifyResult {
  ok: boolean;
  first_bad_seq: number | null;
}

export interface TamperTestResult {
  break_seq: number;
  corrupted_seq: number;
  scratch_rows: number;
  real_chain_ok: boolean;
  audit_seq: number;
}

export function getChain(limit: number, offset: number): Promise<ChainPage> {
  return apiFetch<ChainPage>(`/api/audit/chain?limit=${limit}&offset=${offset}`);
}

export function getVerify(): Promise<VerifyResult> {
  return apiFetch<VerifyResult>("/api/audit/verify");
}

export function postTamperTest(): Promise<TamperTestResult> {
  return apiFetch<TamperTestResult>("/api/audit/tamper-test", {
    method: "POST",
  });
}
