/**
 * Recent-run bookkeeping shared by Discovery (writer) and Case File
 * (reader). sessionStorage only: run ids live exactly as long as the
 * tab, matching the API's in-process run store. No metric values are
 * stored here, only identifiers already returned by POST /api/intake/run.
 */

const KEY = "paritran.recentRuns";
const MAX_ENTRIES = 8;

export interface RecentRun {
  run_id: string;
  seed: number;
  generator: string;
  started_at: string;
}

function isRecentRun(value: unknown): value is RecentRun {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.run_id === "string" &&
    typeof row.seed === "number" &&
    typeof row.generator === "string" &&
    typeof row.started_at === "string"
  );
}

export function listRecentRuns(): RecentRun[] {
  const raw = sessionStorage.getItem(KEY);
  if (raw === null) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isRecentRun);
  } catch {
    return [];
  }
}

export function recordRecentRun(run: RecentRun): void {
  const rows = [
    run,
    ...listRecentRuns().filter((r) => r.run_id !== run.run_id),
  ].slice(0, MAX_ENTRIES);
  sessionStorage.setItem(KEY, JSON.stringify(rows));
}
