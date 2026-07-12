/**
 * Honest placeholder for screens that have not landed yet (truth rule:
 * anything not wired shows an empty state, never fake data). Each
 * instance names the milestone that delivers the real screen.
 */

interface ComingNextProps {
  title: string;
  milestone: string;
  summary: string;
}

export function ComingNext({ title, milestone, summary }: ComingNextProps) {
  return (
    <div className="card" style={{ maxWidth: "38rem" }}>
      <h3>{title}</h3>
      <p style={{ marginTop: 0 }}>{summary}</p>
      <p className="notice-box" style={{ marginBottom: 0 }}>
        This screen lands in <strong>{milestone}</strong>. Nothing is shown
        here until it renders real engine output; placeholders never carry
        data.
      </p>
    </div>
  );
}
