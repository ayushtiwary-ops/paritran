/**
 * Case File endpoint helpers and response types (SPEC 9.1).
 *
 * Every interface mirrors a backend response model field for field:
 * - GET /api/cases/{run_id}/packet -> engine.packet.section63.assemble
 * - POST /api/cases/{run_id}/claims -> routers/cases.py F9Response
 * - GET /api/networks/{idx}?run_id= -> routers/networks.py NetworkOut
 * No number is invented or defaulted here (truth rule 1).
 */

import { apiFetch, type NetworkSummary } from "../../lib/api";

// ---------------------------------------------------------------------------
// Section 63 packet (engine/packet/section63.py assemble() output)

/** Corpus v2 provenance note; section63 defaults to "" when absent. */
export interface SourceNote {
  url?: string;
  page_url?: string;
  accessed?: string;
  edition?: string;
  authoritative_file?: string;
  transform?: string;
}

export interface PacketSection {
  id: string;
  title: string;
  quote_verbatim: string;
  source_note: SourceNote | string;
}

export interface SignatureBlock {
  signature: string;
  place: string;
  date: string;
}

export interface CertificatePart {
  heading: string;
  name: string;
  designation?: string;
  organisation?: string;
  qualification?: string;
  device_or_system?: string;
  case_reference: string;
  draft_statement: string;
  signature_block: SignatureBlock;
}

export interface PacketCertificate {
  part_a: CertificatePart;
  part_b: CertificatePart;
  /** Exact CERTIFICATE_LABEL string from the payload; rendered verbatim. */
  label: string;
}

export interface PacketComplaint {
  id: number;
  intake_hash: string;
}

export interface PacketTrail {
  syndicate: number | null;
  hops: { src: string; dst: string; amount: number }[];
  breaks: string[][];
  traced_amt: number | null;
  total_amt: number | null;
}

export interface PacketF9Verdict {
  section: string;
  quote: string;
  is_fabricated: boolean | null;
  verdict: string;
  sub_class: string | null;
}

export interface PacketF9 {
  generator_name: string | null;
  is_stub: boolean | null;
  corpus_version: string | null;
  claims: number | null;
  passed: number | null;
  withheld: number | null;
  leaked: number | null;
  withheld_sub_classes: Record<string, number>;
  verdicts: PacketF9Verdict[];
}

export interface PacketCustodyRecord {
  rec: Record<string, unknown>;
  prev: string;
  hash: string;
}

export interface Section63Packet {
  case: {
    case_id?: string;
    seed?: number;
    syndicate?: number;
    n_complaints?: number;
    [key: string]: unknown;
  };
  complaints: PacketComplaint[];
  network: { syndicate?: number; size?: number; members?: number[] };
  trail: PacketTrail;
  sections: PacketSection[];
  f9: PacketF9;
  custody_extract: PacketCustodyRecord[];
  certificate: PacketCertificate;
  chain_head: string;
}

export function getPacket(runId: string): Promise<Section63Packet> {
  return apiFetch<Section63Packet>(
    `/api/cases/${encodeURIComponent(runId)}/packet`,
  );
}

// ---------------------------------------------------------------------------
// F9 claims (routers/cases.py F9Response)

export interface F9Verdict {
  section: string;
  quote: string;
  /** Ground-truth label when the generator knows (stub only). */
  is_fabricated: boolean | null;
  verdict: "PASSED" | "WITHHELD";
  sub_class: "invented_section" | "unverifiable_quote" | null;
}

export interface F9Response {
  generator_name: string;
  is_stub: boolean;
  corpus_version: string;
  claims: number;
  passed: number;
  withheld: number;
  leaked: number;
  degraded: boolean;
  verdicts: F9Verdict[];
}

export function runClaims(
  runId: string,
  generator: "stub" | "ollama",
): Promise<F9Response> {
  return apiFetch<F9Response>(
    `/api/cases/${encodeURIComponent(runId)}/claims`,
    { method: "POST", body: JSON.stringify({ generator }) },
  );
}

// ---------------------------------------------------------------------------
// One network in full (routers/networks.py NetworkOut; same shape as the
// list entries, so lib/api.ts NetworkSummary types it exactly)

export function getNetworkDetail(
  runId: string,
  idx: number,
): Promise<NetworkSummary> {
  return apiFetch<NetworkSummary>(
    `/api/networks/${idx}?run_id=${encodeURIComponent(runId)}`,
  );
}
