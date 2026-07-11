import { useEffect, useState, type CSSProperties } from "react";

/**
 * Milestone 1 shell. Every value on this page is either static branding or
 * read verbatim from the live GET /health response (truth rule 1: no number
 * or status is invented between engine and screen). Hero screens, routing,
 * SSE status widget and the rest of SPEC section 10 land in Milestones 5-6.
 */

interface ComponentStatus {
  name: string;
  status: string;
}

type HealthView =
  | { kind: "loading" }
  | { kind: "unreachable"; detail: string }
  | {
      kind: "loaded";
      httpStatus: number;
      overall: string | null;
      components: ComponentStatus[];
    }
  | { kind: "unparsed"; httpStatus: number; bodyText: string };

/** Pull a status string out of whatever shape a component entry has. */
function statusOf(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    if (typeof record.status === "string") return record.status;
    return JSON.stringify(value);
  }
  return String(value);
}

/**
 * Accepts the /health body and extracts per-component statuses without
 * inventing anything. Supports `components` (or `checks`) as either an
 * object keyed by component name or an array of {name, status} entries.
 * Returns null when no such structure exists, in which case the raw body
 * is shown instead.
 */
function extractComponents(body: unknown): ComponentStatus[] | null {
  if (typeof body !== "object" || body === null) return null;
  const record = body as Record<string, unknown>;
  const source = record.components ?? record.checks;

  if (Array.isArray(source)) {
    const out: ComponentStatus[] = [];
    for (const item of source) {
      if (typeof item === "object" && item !== null) {
        const entry = item as Record<string, unknown>;
        if (typeof entry.name === "string") {
          out.push({ name: entry.name, status: statusOf(entry.status ?? entry) });
        }
      }
    }
    return out.length > 0 ? out : null;
  }

  if (typeof source === "object" && source !== null) {
    const out = Object.entries(source as Record<string, unknown>).map(
      ([name, value]) => ({ name, status: statusOf(value) }),
    );
    return out.length > 0 ? out : null;
  }

  return null;
}

function dotColor(status: string): string {
  return status.trim().toLowerCase() === "ok"
    ? "var(--color-forest)"
    : "var(--color-oxblood)";
}

function StatusDot({ color }: { color: string }) {
  return (
    <span
      aria-hidden="true"
      style={{
        display: "inline-block",
        width: "0.6rem",
        height: "0.6rem",
        borderRadius: "50%",
        background: color,
        marginRight: "0.6rem",
        flex: "none",
      }}
    />
  );
}

const monoStyle: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "0.8rem",
};

function HealthCard({ view }: { view: HealthView }) {
  return (
    <section
      aria-live="polite"
      style={{
        background: "var(--color-steel)",
        borderRadius: "6px",
        padding: "1.25rem 1.5rem",
        maxWidth: "26rem",
        width: "100%",
      }}
    >
      <h2
        style={{
          ...monoStyle,
          margin: "0 0 0.9rem",
          fontWeight: 500,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--color-gold)",
        }}
      >
        System components (live from GET /health)
      </h2>

      {view.kind === "loading" && (
        <div style={{ display: "flex", alignItems: "center" }}>
          <StatusDot color="var(--color-muted)" />
          <span style={{ ...monoStyle, color: "var(--color-muted)" }}>
            loading
          </span>
        </div>
      )}

      {view.kind === "unreachable" && (
        <div>
          <div style={{ display: "flex", alignItems: "center" }}>
            <StatusDot color="var(--color-oxblood)" />
            <span style={monoStyle}>api unreachable</span>
          </div>
          <p style={{ ...monoStyle, color: "var(--color-muted)", margin: "0.6rem 0 0" }}>
            {view.detail}
          </p>
        </div>
      )}

      {view.kind === "unparsed" && (
        <div>
          <p style={{ ...monoStyle, margin: "0 0 0.6rem" }}>
            HTTP {view.httpStatus}, body not in the expected component format.
            Raw response:
          </p>
          <pre
            style={{
              ...monoStyle,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              margin: 0,
              color: "var(--color-muted)",
            }}
          >
            {view.bodyText.slice(0, 2000)}
          </pre>
        </div>
      )}

      {view.kind === "loaded" && (
        <div>
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {view.components.map((component) => (
              <li
                key={component.name}
                style={{
                  display: "flex",
                  alignItems: "center",
                  padding: "0.3rem 0",
                }}
              >
                <StatusDot color={dotColor(component.status)} />
                <span style={{ ...monoStyle, marginRight: "0.75rem" }}>
                  {component.name}
                </span>
                <span style={{ ...monoStyle, color: "var(--color-muted)" }}>
                  {component.status}
                </span>
              </li>
            ))}
          </ul>
          <p style={{ ...monoStyle, color: "var(--color-muted)", margin: "0.9rem 0 0" }}>
            HTTP {view.httpStatus}
            {view.overall !== null && <> | overall: {view.overall}</>}
          </p>
        </div>
      )}
    </section>
  );
}

export default function App() {
  const [health, setHealth] = useState<HealthView>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function loadHealth() {
      try {
        const response = await fetch("/health", {
          headers: { Accept: "application/json" },
        });
        const bodyText = await response.text();

        let body: unknown;
        try {
          body = JSON.parse(bodyText);
        } catch {
          if (!cancelled) {
            setHealth({ kind: "unparsed", httpStatus: response.status, bodyText });
          }
          return;
        }

        const components = extractComponents(body);
        if (cancelled) return;

        if (components) {
          const record = body as Record<string, unknown>;
          setHealth({
            kind: "loaded",
            httpStatus: response.status,
            overall: typeof record.status === "string" ? record.status : null,
            components,
          });
        } else {
          setHealth({ kind: "unparsed", httpStatus: response.status, bodyText });
        }
      } catch (error) {
        if (!cancelled) {
          setHealth({
            kind: "unreachable",
            detail: error instanceof Error ? error.message : String(error),
          });
        }
      }
    }

    void loadHealth();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "3rem 1.5rem",
        gap: "2.5rem",
      }}
    >
      <header style={{ textAlign: "center" }}>
        <h1
          style={{
            fontFamily: "var(--font-serif)",
            fontWeight: 600,
            fontSize: "clamp(3rem, 8vw, 5rem)",
            margin: 0,
            letterSpacing: "0.02em",
          }}
        >
          Paritran
        </h1>
        <p
          style={{
            fontFamily: "var(--font-sans)",
            fontSize: "1.1rem",
            color: "var(--color-surface)",
            margin: "0.75rem 0 0",
          }}
        >
          From complaint to conviction
        </p>
        <p
          style={{
            ...monoStyle,
            color: "var(--color-gold)",
            margin: "1.25rem 0 0",
            letterSpacing: "0.08em",
          }}
        >
          Milestone 1 skeleton
        </p>
      </header>

      <HealthCard view={health} />
    </main>
  );
}
