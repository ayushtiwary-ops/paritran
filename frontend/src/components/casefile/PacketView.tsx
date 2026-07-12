/**
 * Section 63 packet rendered as an assembling document (SPEC 10.3
 * screen 2c). Everything shown is a field of GET
 * /api/cases/{run_id}/packet: certificate Parts A and B pre-filled with
 * the payload's values (blank stays visibly blank, never invented), the
 * exact certificate label string, the chain head hash in mono, the
 * custody extract rows, and a Print/Export button (window.print with
 * the @media print rules in app.css).
 */

import { motion } from "motion/react";
import { inr, shortHash } from "../../lib/format";
import type {
  CertificatePart,
  PacketCustodyRecord,
  Section63Packet,
} from "./caseApi";

function Blank({ value, label }: { value: string; label: string }) {
  if (value !== "") return <span>{value}</span>;
  return (
    <span className="cert-blank" aria-label={`${label}: left blank for the signatory`} />
  );
}

function CertPart({
  part,
  reduceMotion,
  delay,
}: {
  part: CertificatePart;
  reduceMotion: boolean;
  delay: number;
}) {
  const fields: [string, string | undefined][] = [
    ["name", part.name],
    ["designation", part.designation],
    ["organisation", part.organisation],
    ["qualification", part.qualification],
    ["device or system", part.device_or_system],
    ["case reference", part.case_reference],
  ];
  return (
    <motion.section
      className="cert-part"
      initial={reduceMotion ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: reduceMotion ? 0 : delay }}
    >
      <h4>{part.heading}</h4>
      <dl className="cert-fields">
        {fields
          .filter((entry): entry is [string, string] => entry[1] !== undefined)
          .map(([label, value]) => (
            <div key={label} style={{ display: "contents" }}>
              <dt>{label}</dt>
              <dd>
                <Blank value={value} label={label} />
              </dd>
            </div>
          ))}
      </dl>
      <p className="cert-statement small">{part.draft_statement}</p>
      <div className="sig-row">
        {(["signature", "place", "date"] as const).map((key) => (
          <div key={key} className="sig-box">
            <span className="field-label">{key}</span>
            {part.signature_block[key] === "" ? (
              <span className="muted small">blank</span>
            ) : (
              <span className="small">{part.signature_block[key]}</span>
            )}
          </div>
        ))}
      </div>
    </motion.section>
  );
}

function custodyLabel(rec: Record<string, unknown>): string {
  const artefact = rec["artefact"];
  if (typeof artefact === "string") return artefact;
  return JSON.stringify(rec);
}

function CustodyRows({ rows }: { rows: PacketCustodyRecord[] }) {
  return (
    <div className="table-scroll">
      <table className="data">
        <thead>
          <tr>
            <th scope="col">record</th>
            <th scope="col">prev</th>
            <th scope="col">hash</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.hash}>
              <td className="mono small">{custodyLabel(row.rec)}</td>
              <td className="mono small" title={row.prev}>
                {shortHash(row.prev)}
              </td>
              <td className="mono small" title={row.hash}>
                {shortHash(row.hash)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface PacketViewProps {
  packet: Section63Packet;
  reduceMotion: boolean;
}

export function PacketView({ packet, reduceMotion }: PacketViewProps) {
  const caseFacts: [string, string][] = Object.entries(packet.case)
    .filter(
      (entry): entry is [string, string | number] =>
        typeof entry[1] === "string" || typeof entry[1] === "number",
    )
    .map(([key, value]) => [key, String(value)]);

  const stagger = (index: number) => (reduceMotion ? 0 : 0.12 * index);

  return (
    <div className="card print-area">
      <div className="packet-head no-print-margin">
        <h3 style={{ margin: 0 }}>Section 63 packet</h3>
        <button
          type="button"
          className="btn no-print"
          onClick={() => window.print()}
        >
          Print / Export
        </button>
      </div>

      <motion.section
        initial={reduceMotion ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: stagger(0) }}
      >
        <dl className="cert-fields" style={{ marginTop: "0.75rem" }}>
          {caseFacts.map(([key, value]) => (
            <div key={key} style={{ display: "contents" }}>
              <dt>{key}</dt>
              <dd className="mono">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="small" style={{ margin: "0.55rem 0 0" }}>
          <span className="muted">custody chain head (anchored out of band): </span>
          <span className="mono packet-chain-head">{packet.chain_head}</span>
        </p>
      </motion.section>

      <motion.section
        initial={reduceMotion ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: stagger(1) }}
      >
        <p className="status-title" style={{ marginTop: "1.1rem" }}>
          BSA Section 63(4) certificate
        </p>
        <p className="notice-box small" style={{ marginTop: 0 }}>
          {packet.certificate.label}
        </p>
      </motion.section>

      <CertPart
        part={packet.certificate.part_a}
        reduceMotion={reduceMotion}
        delay={stagger(2)}
      />
      <CertPart
        part={packet.certificate.part_b}
        reduceMotion={reduceMotion}
        delay={stagger(3)}
      />

      <motion.section
        initial={reduceMotion ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: stagger(4) }}
      >
        <p className="status-title" style={{ marginTop: "1.1rem" }}>
          Sections cited ({packet.sections.length})
        </p>
        <p className="mono small" style={{ margin: 0 }}>
          {packet.sections.map((s) => s.id).join(" . ")}
        </p>

        <p className="status-title" style={{ marginTop: "1.1rem" }}>
          Money trail in packet
        </p>
        <p className="small" style={{ margin: 0 }}>
          {packet.trail.hops.length} hops, {packet.trail.breaks.length} breaks
          {typeof packet.trail.traced_amt === "number" &&
          typeof packet.trail.total_amt === "number"
            ? `, ${inr(packet.trail.traced_amt)} of ${inr(packet.trail.total_amt)} traced`
            : ""}
        </p>

        <p className="status-title" style={{ marginTop: "1.1rem" }}>
          F9 audit embedded in packet
        </p>
        <p className="small mono" style={{ margin: 0 }}>
          generator {packet.f9.generator_name ?? "unknown"} . corpus{" "}
          {packet.f9.corpus_version ?? "unknown"} . passed {packet.f9.passed}
          {" . "}withheld {packet.f9.withheld} . leaked {packet.f9.leaked}
          {packet.f9.is_stub === true ? " . deterministic stub" : ""}
        </p>
      </motion.section>

      <motion.section
        initial={reduceMotion ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: stagger(5) }}
      >
        <p className="status-title" style={{ marginTop: "1.1rem" }}>
          Complaint intake hashes ({packet.complaints.length})
        </p>
        <div className="mapping-scroll mono small">
          <ul className="hash-list">
            {packet.complaints.map((complaint) => (
              <li key={complaint.id} title={complaint.intake_hash}>
                #{complaint.id} {shortHash(complaint.intake_hash, 16, 8)}
              </li>
            ))}
          </ul>
        </div>

        <p className="status-title" style={{ marginTop: "1.1rem" }}>
          Custody extract ({packet.custody_extract.length} records)
        </p>
        <CustodyRows rows={packet.custody_extract} />
      </motion.section>
    </div>
  );
}
