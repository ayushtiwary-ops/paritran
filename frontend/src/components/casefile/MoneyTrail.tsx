/**
 * Money trail: animated SVG value flow victim column -> layered mules ->
 * cash-out (SPEC 10.3 screen 2a). Every node, edge, and amount comes
 * from the network's trail payload (GET /api/networks/{idx}); the
 * run-wide traced percentage comes from the run results. Break edges
 * (missing ledger hops) render in oxblood with a freeze-point chip; when
 * the payload carries no breaks, an honest sub-line explains the
 * untraced remainder instead of inventing any.
 */

import CountUp from "react-countup";
import type { NetworkTrail, TrailHop } from "../../lib/api";
import { inr, pct } from "../../lib/format";

const NODE_W = 152;
const NODE_H = 36;
const COL_GAP = 246;
const ROW_GAP = 74;
const PAD_X = 24;
const PAD_Y = 56;

interface TrailNode {
  name: string;
  x: number;
  y: number;
}

interface TrailLayout {
  nodes: Map<string, TrailNode>;
  layers: string[][];
  width: number;
  height: number;
  maxLayer: number;
}

function buildLayout(trail: NetworkTrail): TrailLayout {
  const edges: { src: string; dst: string }[] = [
    ...trail.hops.map((h) => ({ src: h.src, dst: h.dst })),
    ...trail.breaks
      .filter((b) => b.length >= 2)
      .map((b) => ({ src: b[0] ?? "", dst: b[1] ?? "" })),
  ];

  const order: string[] = [];
  const seen = new Set<string>();
  const add = (name: string) => {
    if (name !== "" && !seen.has(name)) {
      seen.add(name);
      order.push(name);
    }
  };
  for (const e of edges) {
    add(e.src);
    add(e.dst);
  }

  // Longest-path layering: sources sit at 0, every hop pushes its
  // destination one column right. A few relaxation passes converge for
  // the shallow ledgers the engine emits.
  const layerOf = new Map<string, number>(order.map((n) => [n, 0]));
  for (let pass = 0; pass < 8; pass++) {
    for (const e of edges) {
      const ls = layerOf.get(e.src) ?? 0;
      const ld = layerOf.get(e.dst) ?? 0;
      if (ld < ls + 1) layerOf.set(e.dst, ls + 1);
    }
  }

  const maxLayer = Math.max(0, ...order.map((n) => layerOf.get(n) ?? 0));
  const layers: string[][] = Array.from({ length: maxLayer + 1 }, () => []);
  for (const name of order) layers[layerOf.get(name) ?? 0]?.push(name);

  const maxRows = Math.max(1, ...layers.map((l) => l.length));
  const height = PAD_Y + maxRows * ROW_GAP;
  const nodes = new Map<string, TrailNode>();
  layers.forEach((names, layer) => {
    const offset = ((maxRows - names.length) * ROW_GAP) / 2;
    names.forEach((name, row) => {
      nodes.set(name, {
        name,
        x: PAD_X + layer * COL_GAP,
        y: PAD_Y + offset + row * ROW_GAP,
      });
    });
  });

  return {
    nodes,
    layers,
    width: PAD_X * 2 + maxLayer * COL_GAP + NODE_W,
    height,
    maxLayer,
  };
}

function columnLabel(layer: number, maxLayer: number): string {
  if (layer === 0) return "victims";
  if (layer === maxLayer) return "cash-out";
  return `layer ${layer} mules`;
}

function edgePath(a: TrailNode, b: TrailNode): string {
  const x1 = a.x + NODE_W;
  const y1 = a.y + NODE_H / 2;
  const x2 = b.x;
  const y2 = b.y + NODE_H / 2;
  const dx = (x2 - x1) * 0.45;
  return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

interface MoneyTrailProps {
  trail: NetworkTrail;
  /** results.pct_value_traced_to_cashout for the run; null when absent. */
  pctTracedRun: number | null;
  reduceMotion: boolean;
}

export function MoneyTrail({ trail, pctTracedRun, reduceMotion }: MoneyTrailProps) {
  const layoutData = buildLayout(trail);
  const { nodes, layers, width, height, maxLayer } = layoutData;
  const maxAmount = Math.max(1, ...trail.hops.map((h) => h.amount));
  const hopDelay = (index: number) =>
    reduceMotion ? "0s" : `${(index * 0.35).toFixed(2)}s`;

  const renderHop = (hop: TrailHop, index: number) => {
    const a = nodes.get(hop.src);
    const b = nodes.get(hop.dst);
    if (!a || !b) return null;
    const strokeWidth = 1.4 + 2.6 * (hop.amount / maxAmount);
    const midX = (a.x + NODE_W + b.x) / 2;
    const midY = (a.y + b.y) / 2 + NODE_H / 2 - 7;
    return (
      <g key={`hop-${hop.src}-${hop.dst}-${index}`}>
        <path
          d={edgePath(a, b)}
          className="trail-edge"
          pathLength={1}
          strokeWidth={strokeWidth}
          style={{ animationDelay: hopDelay(index) }}
        />
        <text
          x={midX}
          y={midY}
          textAnchor="middle"
          className="trail-amount"
          style={{ animationDelay: hopDelay(index) }}
        >
          {inr(hop.amount)}
        </text>
      </g>
    );
  };

  const renderBreak = (pair: string[], index: number) => {
    const a = nodes.get(pair[0] ?? "");
    const b = nodes.get(pair[1] ?? "");
    if (!a || !b) return null;
    const midX = (a.x + NODE_W + b.x) / 2;
    const midY = (a.y + b.y) / 2 + NODE_H / 2;
    const delay = hopDelay(trail.hops.length + index);
    return (
      <g key={`break-${pair.join("-")}-${index}`}>
        <path
          d={edgePath(a, b)}
          className="trail-break"
          strokeWidth={1.6}
          style={{ animationDelay: delay }}
        />
        <g className="freeze-chip" style={{ animationDelay: delay }}>
          <rect
            x={midX - 44}
            y={midY - 10}
            width={88}
            height={17}
            rx={8.5}
          />
          <text x={midX} y={midY + 2} textAnchor="middle">
            freeze point
          </text>
        </g>
      </g>
    );
  };

  const tracedAmt = trail.traced_amt;
  const totalAmt = trail.total_amt;

  return (
    <div>
      <div className="trail-headline">
        <div>
          <p className="counter-label">Value traced to cash-out (run-wide)</p>
          <p className="counter-value">
            {pctTracedRun !== null ? (
              <CountUp
                end={pctTracedRun}
                decimals={1}
                suffix="%"
                duration={reduceMotion ? 0 : 1.8}
                preserveValue
              />
            ) : (
              <span className="muted">not in results</span>
            )}
          </p>
          <p className="counter-sub">metric: pct_value_traced_to_cashout</p>
        </div>
        <div>
          <p className="counter-label">This network</p>
          <p className="counter-value">{inr(tracedAmt)}</p>
          <p className="counter-sub">
            of {inr(totalAmt)} complaint value . {trail.hops.length} ledger hop
            {trail.hops.length === 1 ? "" : "s"} . syndicate {trail.syndicate}
          </p>
        </div>
      </div>

      <div className="table-scroll">
        <svg
          className="trail-svg"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={`Money trail with ${trail.hops.length} hops and ${trail.breaks.length} break edges`}
        >
          {layers.map((names, layer) =>
            names.length > 0 ? (
              <text
                key={`col-${layer}`}
                x={PAD_X + layer * COL_GAP + NODE_W / 2}
                y={26}
                textAnchor="middle"
                className="trail-col-label"
              >
                {columnLabel(layer, maxLayer)}
              </text>
            ) : null,
          )}
          {trail.hops.map(renderHop)}
          {trail.breaks.map(renderBreak)}
          {[...nodes.values()].map((node) => (
            <g key={node.name} className="trail-node">
              <rect
                x={node.x}
                y={node.y}
                width={NODE_W}
                height={NODE_H}
                rx={6}
              />
              <text
                x={node.x + NODE_W / 2}
                y={node.y + NODE_H / 2 + 4}
                textAnchor="middle"
              >
                {node.name}
              </text>
            </g>
          ))}
        </svg>
      </div>

      {trail.breaks.length === 0 ? (
        <p className="notice-box small" style={{ marginBottom: 0 }}>
          No break edges in this network at this seed: every ledger hop to
          cash-out is present, so there is no freeze point to flag here
          {typeof tracedAmt === "number" && typeof totalAmt === "number"
            ? ` (${inr(tracedAmt)} of ${inr(totalAmt)} traced)`
            : ""}
          .
          {pctTracedRun !== null &&
            ` Run-wide, ${pct(pctTracedRun)} of complaint value traced to` +
              ` cash-out; the untraced ${pct(100 - pctTracedRun)} is value` +
              " the reachability walk never reached a cash-out account for" +
              " (results totals), not a break in this network."}
        </p>
      ) : (
        <p className="counter-sub" style={{ marginBottom: 0 }}>
          {trail.breaks.length} break edge
          {trail.breaks.length === 1 ? "" : "s"} flagged in oxblood: missing
          ledger hops, each a freeze opportunity.
        </p>
      )}
    </div>
  );
}
