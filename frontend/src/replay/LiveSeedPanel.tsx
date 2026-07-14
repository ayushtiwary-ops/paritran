import { useEffect, useRef, useState } from "react";
import { Badge } from "./labels";

type Results = Record<string, number | string | boolean>;

type WorkerOut =
  | { type: "progress"; label: string; loaded: number; total: number }
  | { type: "stage"; stage: string }
  | { type: "result"; seed: number; results: Results; loadedFrom: string | null }
  | { type: "error"; message: string };

// Pinned forever (SPEC_HOSTED_APP 2.3). Never the rolling channel, never bumped for 13 days.
const PYODIDE_CDN = "https://cdn.jsdelivr.net/pyodide/v314.0.2/full/";
const REPO_ENGINE_URL = "https://github.com/ayushtiwary-ops/paritran/blob/main/src/paritran_prototype.py";

const NUMERIC_FIELDS = [
  "n_complaints",
  "n_syndicates_seeded",
  "networks_found",
  "linkage_precision",
  "linkage_recall",
  "linkage_f1",
  "pct_value_traced_to_cashout",
  "section_accuracy_bm25",
  "f9_claims",
  "f9_passed",
  "f9_withheld_stub_fabrications",
  "f9_leaked",
  "chain_len",
  "time_to_packet_sec",
] as const;
const BOOL_FIELDS = ["chain_verified", "tamper_detected"] as const;
const STRING_FIELDS = ["money_trail_method", "section_method", "data"] as const;

// The 19 comparison fields for the seed-42 reproduction ticks: all 20 keys
// except the wall-clock time_to_packet_sec (SPEC_HOSTED_APP S2, A4).
const COMPARE_FIELDS: string[] = [
  ...NUMERIC_FIELDS.filter((field) => field !== "time_to_packet_sec"),
  ...BOOL_FIELDS,
  ...STRING_FIELDS,
  "seed",
];

const LABELS: Record<string, string> = {
  n_complaints: "Complaints ingested",
  n_syndicates_seeded: "Syndicates seeded (ground truth)",
  networks_found: "Mule networks found",
  linkage_precision: "Linkage precision",
  linkage_recall: "Linkage recall",
  linkage_f1: "Linkage F1",
  pct_value_traced_to_cashout: "Value traced to cash-out (%)",
  section_accuracy_bm25: "Section mapping, BM25 floor (%)",
  f9_claims: "F9 claims checked",
  f9_passed: "F9 claims passed",
  f9_withheld_stub_fabrications: "F9 stub fabrications withheld",
  f9_leaked: "F9 fabrications leaked",
  chain_len: "Custody chain length",
  time_to_packet_sec: "Time to packet (this run)",
  chain_verified: "Custody chain verified",
  tamper_detected: "Tamper detected on scratch copy",
  money_trail_method: "Money-trail method",
  section_method: "Section-mapping method",
  data: "Data provenance",
};

function fmtValue(value: number | string | boolean | undefined): string {
  if (value === undefined) return "n/a";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

function fmtMB(bytes: number): string {
  return (bytes / 1_000_000).toFixed(1);
}

async function sha256Hex(text: string): Promise<string> {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export function LiveSeedPanel() {
  const [seedText, setSeedText] = useState("42");
  const [running, setRunning] = useState(false);
  const [stage, setStage] = useState("");
  const [progress, setProgress] = useState<{ label: string; loaded: number; total: number } | null>(null);
  const [results, setResults] = useState<Results | null>(null);
  const [usedSeed, setUsedSeed] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<Array<{ seed: number; f1: number; traced: number; networks: number }>>([]);
  const [baseline, setBaseline] = useState<Results | null>(null);
  const [engineSource, setEngineSource] = useState<string | null>(null);
  const [engineSha, setEngineSha] = useState<string | null>(null);
  const [wasmOk, setWasmOk] = useState(true);
  const workerRef = useRef<Worker | null>(null);

  useEffect(() => {
    setWasmOk(typeof WebAssembly === "object");
    const base = import.meta.env.BASE_URL;
    const refUrl = new URL(base + "py/results.reference.json", window.location.origin).href;
    const pyUrl = new URL(base + "py/paritran_prototype.py", window.location.origin).href;
    fetch(refUrl)
      .then((response) => response.json())
      .then((json: Results) => setBaseline(json))
      .catch(() => setBaseline(null));
    fetch(pyUrl)
      .then((response) => response.text())
      .then(async (text) => {
        setEngineSource(text);
        setEngineSha(await sha256Hex(text));
      })
      .catch(() => setEngineSource(null));
    return () => {
      workerRef.current?.terminate();
      workerRef.current = null;
    };
  }, []);

  function ensureWorker(): Worker {
    const existing = workerRef.current;
    if (existing) return existing;
    const worker = new Worker(new URL("./pyWorker.ts", import.meta.url), { type: "module" });
    worker.onmessage = (event: MessageEvent<WorkerOut>) => {
      const message = event.data;
      if (message.type === "progress") {
        setProgress({ label: message.label, loaded: message.loaded, total: message.total });
      } else if (message.type === "stage") {
        setStage(message.stage);
      } else if (message.type === "error") {
        setError(message.message);
        setRunning(false);
        setProgress(null);
        setStage("");
      } else {
        setResults(message.results);
        setUsedSeed(message.seed);
        setRunning(false);
        setProgress(null);
        setStage("");
        const f1 = typeof message.results.linkage_f1 === "number" ? message.results.linkage_f1 : 0;
        const traced =
          typeof message.results.pct_value_traced_to_cashout === "number"
            ? message.results.pct_value_traced_to_cashout
            : 0;
        const networks = typeof message.results.networks_found === "number" ? message.results.networks_found : 0;
        setHistory((prev) => [{ seed: message.seed, f1, traced, networks }, ...prev].slice(0, 8));
      }
    };
    workerRef.current = worker;
    return worker;
  }

  function runNow(): void {
    setError(null);
    const seed = Number(seedText);
    if (!Number.isInteger(seed) || seed < 0 || seed > 4294967295) {
      setError("Enter an integer seed between 0 and 4294967295.");
      return;
    }
    const base = import.meta.env.BASE_URL;
    const vendorBase = new URL(base + "vendor/pyodide/", window.location.origin).href;
    const pyUrl = new URL(base + "py/paritran_prototype.py", window.location.origin).href;
    setRunning(true);
    setStage("preparing");
    setProgress(null);
    ensureWorker().postMessage({ type: "run", seed, vendorBase, cdnBase: PYODIDE_CDN, pyUrl });
  }

  if (!wasmOk) {
    return (
      <div className="live-panel">
        <div className="live-head">
          <Badge kind="LIVE" />
          <h3>Judge's seed</h3>
        </div>
        <p className="error">
          Your browser blocks WebAssembly, so the live run is unavailable here. The recorded replay above is unaffected,
          and the same engine can be run from the repository with one command:{" "}
          <code>python3 src/paritran_prototype.py</code>. <a href={REPO_ENGINE_URL}>View the engine</a>.
        </p>
      </div>
    );
  }

  const allMatch =
    baseline != null && results != null && COMPARE_FIELDS.every((field) => results[field] === baseline[field]);
  const showReproBanner = usedSeed === 42 && allMatch;

  return (
    <div className="live-panel">
      <div className="live-head">
        <Badge kind="LIVE" />
        <h3>Judge's seed: run the real engine on your device</h3>
      </div>
      <p className="hint">
        The same 240-line engine that produced the frozen <code>results.json</code> runs here, in your browser, with no
        server. Type any seed and rerun it. No number on this page is canned: change the seed and the network metrics
        move.
      </p>
      <div className="seed-row">
        <label htmlFor="seed">Seed</label>
        <input
          id="seed"
          className="seed-input"
          inputMode="numeric"
          value={seedText}
          onChange={(event) => setSeedText(event.target.value)}
          disabled={running}
        />
        <button className="run-btn" onClick={runNow} disabled={running}>
          {running ? "Running..." : "Run in my browser"}
        </button>
      </div>
      <p className="hint">
        First run downloads the Python runtime (about 13 MB, one time, cached after). Every later run takes about a
        tenth of a second.
      </p>

      {running && (
        <div className="progress" aria-live="polite">
          {progress && progress.total > 0 && (
            <>
              <div className="bar">
                <span style={{ width: `${Math.min(100, (progress.loaded / progress.total) * 100)}%` }} />
              </div>
              <div className="stage">
                {progress.label}: {fmtMB(progress.loaded)} / {fmtMB(progress.total)} MB
              </div>
            </>
          )}
          {stage && <div className="stage">{stage}</div>}
        </div>
      )}

      {error && (
        <p className="error" aria-live="assertive">
          {error}
        </p>
      )}

      {results && !running && (
        <>
          {showReproBanner ? (
            <div className="banner-ok" aria-live="polite">
              Seed 42 reproduces the frozen results.json exactly, field by field, in your browser (
              {COMPARE_FIELDS.length} fields checked, all equal; the wall-clock time is measured live and excluded).
            </div>
          ) : (
            <div className="note">
              Seed {usedSeed}: the engine ran live in your browser. Seed-dependent metrics differ from the frozen
              seed-42 baseline; the deterministic ones do not.
            </div>
          )}

          <div className="metric-grid">
            <div className="metric-card">
              <div className="k">Seed (from your input)</div>
              <div className="v mono">{usedSeed}</div>
            </div>

            {NUMERIC_FIELDS.filter((field) => field !== "time_to_packet_sec").map((field) => {
              const value = results[field];
              const base = baseline ? baseline[field] : undefined;
              const delta =
                typeof value === "number" && typeof base === "number"
                  ? Math.round((value - base) * 1000) / 1000
                  : null;
              return (
                <div className="metric-card" key={field}>
                  <div className="k">{LABELS[field] ?? field}</div>
                  <div className="v">{fmtValue(value)}</div>
                  {delta === null ? null : delta === 0 ? (
                    <span className="delta eq">= frozen baseline</span>
                  ) : (
                    <span className="delta mv">
                      {delta > 0 ? "+" : ""}
                      {delta} vs seed 42
                    </span>
                  )}
                </div>
              );
            })}

            <div className="metric-card special">
              <div className="k">{LABELS["time_to_packet_sec"]}</div>
              <div className="v">{fmtValue(results["time_to_packet_sec"])} s</div>
              <span className="delta">
                native on-premise reference {baseline ? fmtValue(baseline["time_to_packet_sec"]) : "0.045"} s (frozen);
                wall clock, not compared
              </span>
            </div>

            {BOOL_FIELDS.map((field) => (
              <div className="metric-card" key={field}>
                <div className="k">{LABELS[field] ?? field}</div>
                <div className="v">{fmtValue(results[field])}</div>
                {baseline && results[field] === baseline[field] ? (
                  <span className="delta eq">= frozen baseline</span>
                ) : null}
              </div>
            ))}

            {STRING_FIELDS.map((field) => (
              <div className="metric-card" key={field}>
                <div className="k">{LABELS[field] ?? field}</div>
                <div className="v mono">{fmtValue(results[field])}</div>
              </div>
            ))}
          </div>

          <div className="stub-note">
            <Badge kind="STUB" />
            <span>
              The generator in this slice is the labelled deterministic stub: it emits 50 claims and fabricates 10 on
              purpose, so the F9 gate is exercised against known fabrications (40 passed, 10 withheld, 0 leaked). The
              production path uses a local gemma3:4b via Ollama with zero egress.
            </span>
          </div>

          <p className="note">
            By construction, some metrics are deterministic and do not move with the seed: the F9 stub emits exactly 50
            claims (40 passed, 10 withheld stub fabrications, 0 leaked), the corpus v1 accuracy is 52.4, and the custody
            chain is 12 records. The network metrics (complaints, networks found, precision, recall, F1, % value traced)
            are seed-dependent and will move. Type a different seed and watch them change.
          </p>

          {history.length > 0 && (
            <table className="runhist">
              <thead>
                <tr>
                  <th>seed</th>
                  <th>F1</th>
                  <th>% traced</th>
                  <th>networks</th>
                </tr>
              </thead>
              <tbody>
                {history.map((entry, index) => (
                  <tr key={`${entry.seed}-${index}`}>
                    <td>{entry.seed}</td>
                    <td>{entry.f1}</td>
                    <td>{entry.traced}</td>
                    <td>{entry.networks}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <details className="codeview">
            <summary>View the exact code you just ran</summary>
            {engineSha && (
              <p className="sha">
                SHA-256 of the engine file: {engineSha}. Byte-identical to the repository file, enforced by CI.{" "}
                <a href={REPO_ENGINE_URL}>Open it on GitHub</a>.
              </p>
            )}
            <p className="hint">
              Two client-side shims are applied, shown literally: the seed line is replaced, and the engine writes its
              results to an in-browser virtual filesystem rather than to disk.
            </p>
            <pre>{`- random.seed(42)\n+ random.seed(${usedSeed})\n\n# results.json is written to /home/pyodide/results.json (in-browser MEMFS),\n# never to the repository file.`}</pre>
            {engineSource && <pre>{engineSource}</pre>}
          </details>
        </>
      )}
    </div>
  );
}
