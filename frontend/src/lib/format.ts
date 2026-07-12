/**
 * Display formatting only. Nothing here computes a metric; every function
 * renders a value that arrived in an API or SSE payload (truth rule 1).
 */

const inrFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

const numberFormatter = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 3,
});

/** Rupees with Indian digit grouping, e.g. 1234567 -> "₹12,34,567". */
export function inr(value: number): string {
  return inrFormatter.format(value);
}

/** Plain number with en-IN grouping. */
export function num(value: number): string {
  return numberFormatter.format(value);
}

/** Percentage display; the value is already a percent (e.g. 61.9). */
export function pct(value: number, digits = 1): string {
  return `${value.toFixed(digits)}%`;
}

/** Shorten a hex hash for display: leading 10 + trailing 6 characters. */
export function shortHash(hash: string, lead = 10, tail = 6): string {
  if (hash.length <= lead + tail + 2) return hash;
  return `${hash.slice(0, lead)}..${hash.slice(-tail)}`;
}

/** ISO timestamp -> local, seconds precision. */
export function fmtTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Milliseconds for compact display. */
export function fmtMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${ms.toFixed(ms < 10 ? 1 : 0)} ms`;
}
