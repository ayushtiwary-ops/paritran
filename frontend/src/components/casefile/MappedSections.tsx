/**
 * Mapped sections panel (SPEC 10.3 screen 2b).
 *
 * Two real sources, joined, nothing synthesized:
 * - packet sections (GET /api/cases/{run_id}/packet): the verbatim
 *   corpus v2 quote and its source_note (url + accessed), rendered as a
 *   clickable reference;
 * - per-complaint mapping.section events replayed from the run stream
 *   (the /api/networks/{idx} payload carries no mapping rows, so the
 *   stored SSE events are the per-complaint source): sections,
 *   confidence, routed_to_human, exactly as the engine emitted them.
 */

import { motion } from "motion/react";
import type { RunEventMap } from "../../lib/sse";
import type { PacketSection, SourceNote } from "./caseApi";

export type MappingSectionEvent = RunEventMap["mapping.section"];

function sourceLink(note: SourceNote | string) {
  if (typeof note === "string") {
    return note === "" ? (
      <span className="muted">no source note in payload</span>
    ) : (
      <span>{note}</span>
    );
  }
  const label = note.accessed
    ? `India Code, accessed ${note.accessed}`
    : "India Code source";
  return (
    <span>
      {typeof note.url === "string" ? (
        <a href={note.url} target="_blank" rel="noreferrer">
          {label}
        </a>
      ) : (
        <span>{label}</span>
      )}
      {typeof note.edition === "string" && (
        <span className="muted"> . {note.edition}</span>
      )}
    </span>
  );
}

function ConfidenceChip({
  confidence,
  routedToHuman,
}: {
  confidence: string;
  routedToHuman: boolean;
}) {
  const high = confidence === "HIGH";
  return (
    <span className={`conf-chip ${high ? "high" : "low"}`}>
      {confidence}
      {!high && routedToHuman ? " . routed to human" : ""}
    </span>
  );
}

interface MappedSectionsProps {
  sections: PacketSection[];
  /** null while the stored run events are still replaying. */
  mappings: MappingSectionEvent[] | null;
  /** Complaint ids belonging to the selected network. */
  members: number[];
  streamError: boolean;
  reduceMotion: boolean;
}

export function MappedSections({
  sections,
  mappings,
  members,
  streamError,
  reduceMotion,
}: MappedSectionsProps) {
  const memberSet = new Set(members);
  const networkMappings =
    mappings === null
      ? null
      : mappings.filter((m) => memberSet.has(m.complaint_id));

  return (
    <div className="card">
      <h3>Mapped sections (verbatim corpus v2)</h3>

      {sections.length === 0 ? (
        <p className="muted small" style={{ margin: 0 }}>
          The packet carries no cited sections for this run.
        </p>
      ) : (
        <ul className="section-list">
          {sections.map((section, index) => (
            <motion.li
              key={section.id}
              className="section-entry"
              initial={reduceMotion ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: reduceMotion ? 0 : index * 0.08 }}
            >
              <div className="section-head">
                <span className="mono section-id">{section.id}</span>
                <span>{section.title}</span>
              </div>
              <details>
                <summary className="small">verbatim v2 text</summary>
                <blockquote className="section-quote small">
                  {section.quote_verbatim}
                </blockquote>
              </details>
              <p className="small" style={{ margin: "0.3rem 0 0" }}>
                {sourceLink(section.source_note)}
              </p>
            </motion.li>
          ))}
        </ul>
      )}

      <p className="status-title" style={{ margin: "1rem 0 0.45rem" }}>
        Per-complaint mapping (this network)
      </p>
      {streamError && (
        <p className="error-box small" style={{ margin: 0 }}>
          Could not replay the run's mapping events; the cited sections
          above are still the packet's. Reload to retry the replay.
        </p>
      )}
      {!streamError && networkMappings === null && (
        <p className="muted small" style={{ margin: 0 }}>
          Replaying stored mapping.section events for this run.
        </p>
      )}
      {networkMappings !== null && networkMappings.length === 0 && (
        <p className="muted small" style={{ margin: 0 }}>
          No mapping events for this network's complaints in the run
          stream.
        </p>
      )}
      {networkMappings !== null && networkMappings.length > 0 && (
        <div className="mapping-scroll">
          <table className="data">
            <thead>
              <tr>
                <th scope="col">complaint</th>
                <th scope="col">sections</th>
                <th scope="col">confidence</th>
              </tr>
            </thead>
            <tbody>
              {networkMappings.map((row) => (
                <tr key={row.complaint_id}>
                  <td className="num">{row.complaint_id}</td>
                  <td className="mono small">{row.sections.join(" . ")}</td>
                  <td>
                    <ConfidenceChip
                      confidence={row.confidence}
                      routedToHuman={row.routed_to_human}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
