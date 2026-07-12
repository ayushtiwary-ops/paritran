/**
 * Presentational collapsing force graph for the demo hero (SPEC 10.3 item
 * 1, SPEC 14 beat 2). Fed the paced graph data by Demo.tsx; it draws the
 * canvas and colors communities. No data lives here: every node and edge
 * arrived on the run stream as graph.node.added / graph.edge.added /
 * network.discovered events.
 */

import { useEffect, useRef, useState } from "react";
import ForceGraph2D, {
  type ForceGraphMethods,
  type LinkObject,
  type NodeObject,
} from "react-force-graph-2d";

export interface DemoNodeDatum {
  id: number;
  community: number | null;
}
export interface DemoLinkDatum {
  w: number;
}

type GNode = NodeObject<DemoNodeDatum>;
type GLink = LinkObject<DemoNodeDatum, DemoLinkDatum>;

/** Distinct community hues that sit on the navy canvas; noise is muted. */
const COMMUNITY_COLORS = [
  "#3E9E9F",
  "#C98D3D",
  "#4C9A72",
  "#6FA8DC",
  "#C06C6C",
  "#9B7FC7",
  "#D4B26A",
  "#5BBFA5",
];
const UNASSIGNED_COLOR = "#FBFAF6";

export function communityColor(community: number | null): string {
  if (community === null) return UNASSIGNED_COLOR;
  return COMMUNITY_COLORS[community % COMMUNITY_COLORS.length] ?? UNASSIGNED_COLOR;
}

interface DemoGraphProps {
  nodes: GNode[];
  links: GLink[];
  reduceMotion: boolean;
  streaming: boolean;
}

export function DemoGraph({ nodes, links, reduceMotion, streaming }: DemoGraphProps) {
  const graphRef = useRef<ForceGraphMethods<GNode, GLink> | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 640, height: 460 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      setSize({
        width: Math.max(entry.contentRect.width, 200),
        height: Math.max(entry.contentRect.height, 320),
      });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="card graph-panel" ref={containerRef} style={{ height: "460px" }}>
      <div className="graph-overlay">
        {nodes.length > 0 && (
          <span>
            {nodes.length} nodes . {links.length} links
            {streaming ? " . collapsing" : ""}
          </span>
        )}
      </div>
      {nodes.length === 0 && (
        <div className="graph-empty">
          The linkage graph streams in here, complaint by complaint, and
          collapses into mule networks as the run proceeds.
        </div>
      )}
      <ForceGraph2D<DemoNodeDatum, DemoLinkDatum>
        ref={graphRef}
        width={size.width}
        height={size.height}
        graphData={{ nodes, links }}
        backgroundColor="rgba(0,0,0,0)"
        nodeColor={(node) => communityColor(node.community ?? null)}
        nodeRelSize={3.2}
        nodeLabel={(node) =>
          `complaint ${String(node.id)}${
            typeof node.community === "number"
              ? ` . network ${node.community}`
              : " . unassigned"
          }`
        }
        linkColor={() => "rgba(251, 250, 246, 0.22)"}
        linkWidth={(link) => Math.min(1 + link.w * 0.4, 3)}
        cooldownTicks={reduceMotion ? 0 : undefined}
        d3VelocityDecay={0.35}
      />
    </div>
  );
}

export type { GNode as DemoGNode, GLink as DemoGLink };
