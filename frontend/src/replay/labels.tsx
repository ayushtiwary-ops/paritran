// REPLAY / LIVE / STUB provenance badges and the header legend.
// Exact copy per SPEC_HOSTED_APP.md Section 1 (honesty rule d): every panel
// carries its provenance badge, and the legend explains all three up front.

type Kind = "REPLAY" | "LIVE" | "STUB";

const CHIP_CLASS: Record<Kind, string> = {
  REPLAY: "chip chip-replay",
  LIVE: "chip chip-live",
  STUB: "chip chip-stub",
};

export function Badge({ kind }: { kind: Kind }) {
  return <span className={CHIP_CLASS[kind]}>{kind}</span>;
}

const LEGEND: Array<{ kind: Kind; text: string }> = [
  {
    kind: "REPLAY",
    text:
      "recorded from a real seed-42 run of the full on-premise stack on the demo machine. These panels replay stored events. Nothing in them is recomputed on this page.",
  },
  {
    kind: "LIVE",
    text:
      "computed in your browser, seconds ago, by the same pipeline code that is in the repository. No data leaves this page.",
  },
  {
    kind: "STUB",
    text:
      "a deterministic stand-in for the local LLM. It fabricates on purpose, with ground-truth labels, so the F9 gate is exercised against known fabrications.",
  },
];

export function Legend() {
  return (
    <div className="legend">
      {LEGEND.map(({ kind, text }) => (
        <div className="legend-row" key={kind}>
          <Badge kind={kind} />
          <span className="legend-text">{text}</span>
        </div>
      ))}
    </div>
  );
}
