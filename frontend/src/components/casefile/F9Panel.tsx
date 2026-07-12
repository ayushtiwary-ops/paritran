/**
 * F9 groundedness audit panel (SPEC 10.3 screen 2d).
 *
 * POST /api/cases/{run_id}/claims with the chosen generator; verdicts
 * tick in with motion (PASSED forest, WITHHELD oxblood with its
 * sub_class chip). The counters and every label (generator name,
 * is_stub, degraded) come from the response and sit next to the numbers
 * at all times (truth rule: no F9 number without its generator label).
 * The withheld counter announces assertively (SPEC 10.4).
 */

import { motion } from "motion/react";
import { useEffect, useState } from "react";
import CountUp from "react-countup";
import { pushToast } from "../../app/toasts";
import { ApiError } from "../../lib/api";
import { runClaims, type F9Response, type F9Verdict } from "./caseApi";

const TICK_MS = 60;

function VerdictRow({
  verdict,
  reduceMotion,
}: {
  verdict: F9Verdict;
  reduceMotion: boolean;
}) {
  const withheld = verdict.verdict === "WITHHELD";
  return (
    <motion.li
      className={`verdict-row ${withheld ? "withheld" : "passed"}`}
      initial={reduceMotion ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <span className={`verdict-chip ${withheld ? "withheld" : "passed"}`}>
        {verdict.verdict}
      </span>
      <span className="mono small">{verdict.section}</span>
      <span className="small verdict-quote">"{verdict.quote}"</span>
      {verdict.sub_class !== null && (
        <span className="conf-chip low">{verdict.sub_class}</span>
      )}
    </motion.li>
  );
}

interface F9PanelProps {
  runId: string;
  reduceMotion: boolean;
}

export function F9Panel({ runId, reduceMotion }: F9PanelProps) {
  const [generator, setGenerator] = useState<"stub" | "ollama">("stub");
  const [auditing, setAuditing] = useState(false);
  const [result, setResult] = useState<F9Response | null>(null);
  const [revealed, setRevealed] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Reveal verdicts one by one so the audit visibly ticks; reduced
  // motion shows everything at once. Pacing changes WHEN verdicts
  // paint, never WHAT they say.
  useEffect(() => {
    if (result === null) return;
    if (reduceMotion) {
      setRevealed(result.verdicts.length);
      return;
    }
    if (revealed >= result.verdicts.length) return;
    const timer = setInterval(
      () => setRevealed((n) => Math.min(n + 1, result.verdicts.length)),
      TICK_MS,
    );
    return () => clearInterval(timer);
  }, [result, revealed, reduceMotion]);

  const onRun = async () => {
    if (auditing) return;
    setAuditing(true);
    setError(null);
    setResult(null);
    setRevealed(0);
    try {
      const response = await runClaims(runId, generator);
      setResult(response);
      if (response.degraded) {
        pushToast({
          title: "Ollama unreachable; deterministic stub ran instead",
          detail: `generator ${response.generator_name}, degraded=true`,
          tone: "danger",
          assertive: true,
        });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setAuditing(false);
    }
  };

  return (
    <div className="card">
      <h3>F9 groundedness audit</h3>
      <div className="f9-controls">
        <div>
          <label className="field-label" htmlFor="f9-generator">
            Generator
          </label>
          <select
            id="f9-generator"
            className="select"
            value={generator}
            onChange={(e) =>
              setGenerator(e.target.value === "ollama" ? "ollama" : "stub")
            }
            disabled={auditing}
          >
            <option value="stub">stub (deterministic, labelled)</option>
            <option value="ollama">ollama (live model)</option>
          </select>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => void onRun()}
          disabled={auditing}
        >
          {auditing ? "Auditing" : "Run F9 audit"}
        </button>
        {auditing && generator === "ollama" && (
          <span className="muted small">
            live model call; this can take a while
          </span>
        )}
      </div>

      {error !== null && (
        <p className="error-box small" role="alert">
          F9 audit failed: {error}
        </p>
      )}

      {result === null && error === null && !auditing && (
        <p className="muted small" style={{ margin: "0.75rem 0 0" }}>
          No audit run yet. Every claim the generator emits passes the
          verbatim gate or is withheld; nothing renders until the
          response arrives.
        </p>
      )}

      {result !== null && (
        <div style={{ marginTop: "0.85rem" }}>
          {/* Generator label ALWAYS next to the numbers (SPEC 6.8). */}
          <p className="mono small f9-generator-line">
            generator <strong>{result.generator_name}</strong> . corpus{" "}
            {result.corpus_version} .{" "}
            {result.is_stub ? "deterministic stub" : "live model"}
            {result.degraded && (
              <span className="conf-chip low" style={{ marginLeft: "0.5rem" }}>
                degraded: ollama unreachable, stub ran
              </span>
            )}
          </p>
          <div className="counter-row" style={{ margin: "0.6rem 0 0.85rem" }}>
            <div>
              <p className="counter-label">Passed</p>
              <p className="counter-value f9-passed">
                <CountUp
                  end={result.passed}
                  duration={reduceMotion ? 0 : 1}
                  preserveValue
                />
              </p>
            </div>
            <div aria-live="assertive">
              <p className="counter-label">Withheld</p>
              <p className="counter-value f9-withheld">
                <CountUp
                  end={result.withheld}
                  duration={reduceMotion ? 0 : 1}
                  preserveValue
                />
              </p>
            </div>
            <div>
              <p className="counter-label">Leaked</p>
              <p className="counter-value">
                <CountUp
                  end={result.leaked}
                  duration={reduceMotion ? 0 : 1}
                  preserveValue
                />
              </p>
            </div>
            <div>
              <p className="counter-label">Claims</p>
              <p className="counter-value">
                <CountUp
                  end={result.claims}
                  duration={reduceMotion ? 0 : 1}
                  preserveValue
                />
              </p>
            </div>
          </div>
          <ul className="verdict-list" aria-label="F9 verdicts">
            {result.verdicts.slice(0, revealed).map((verdict, index) => (
              <VerdictRow
                key={`${verdict.section}-${index}`}
                verdict={verdict}
                reduceMotion={reduceMotion}
              />
            ))}
          </ul>
          {revealed < result.verdicts.length && (
            <p className="muted small" style={{ margin: "0.4rem 0 0" }}>
              {revealed} of {result.verdicts.length} verdicts shown
            </p>
          )}
        </div>
      )}
    </div>
  );
}
