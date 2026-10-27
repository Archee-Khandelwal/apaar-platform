"use client";

/**
 * Cytoscape view of one cluster. Students are circles coloured by institution;
 * shared contacts are larger diamonds. Every label is masked, and a contact is
 * "Guardian contact #1", never a number or a hash.
 *
 * The layout runs without animation: it settles instantly for a screenshot, and
 * it removes the race where unmounting mid-animation tears down the core while
 * the layout is still notifying it.
 */
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { useEffect, useMemo, useRef } from "react";

import type { ClusterDetail, GraphNode } from "@/lib/types";
import { cn } from "@/lib/utils";

const INSTITUTION_COLOURS = ["#1e40af", "#0e7490", "#7c3aed", "#b45309", "#be123c", "#15803d"];
const CONTACT_COLOUR = "#0284c7";

export function institutionColours(nodes: GraphNode[]): Map<string, string> {
  const names = Array.from(
    new Set(nodes.filter((node) => node.data.type === "student").map((node) => node.data.institution ?? "—")),
  );
  return new Map(names.map((name, index) => [name, INSTITUTION_COLOURS[index % INSTITUTION_COLOURS.length]]));
}

export function ClusterGraph({
  cluster,
  onSelectStudent,
  height = 460,
  className,
}: {
  cluster: ClusterDetail;
  onSelectStudent?: (node: GraphNode["data"] | null) => void;
  height?: number;
  className?: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<Core | null>(null);
  const colours = useMemo(() => institutionColours(cluster.nodes), [cluster.nodes]);

  useEffect(() => {
    if (!container.current) return;

    const elements: ElementDefinition[] = [
      ...cluster.nodes.map((node) => ({
        data: {
          ...node.data,
          colour:
            node.data.type === "student"
              ? (colours.get(node.data.institution ?? "—") ?? INSTITUTION_COLOURS[0])
              : CONTACT_COLOUR,
        },
      })),
      ...cluster.edges.map((edge) => ({ data: { ...edge.data } })),
    ];

    const core = cytoscape({
      container: container.current,
      elements,
      style: [
        {
          selector: "node[type = 'student']",
          style: {
            "background-color": "data(colour)",
            label: "data(label)",
            "font-size": 8,
            color: "#334155",
            "text-valign": "bottom",
            "text-margin-y": 3,
            width: 22,
            height: 22,
            "border-width": 1.5,
            "border-color": "#ffffff",
          },
        },
        {
          selector: "node[type != 'student']",
          style: {
            "background-color": CONTACT_COLOUR,
            shape: "diamond",
            label: "data(label)",
            "font-size": 10,
            "font-weight": 600,
            color: "#075985",
            "text-valign": "center",
            "text-halign": "right",
            "text-margin-x": 6,
            width: 44,
            height: 44,
            "border-width": 2,
            "border-color": "#ffffff",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.2,
            "line-color": "#cbd5e1",
            "curve-style": "haystack",
            opacity: 0.8,
          },
        },
        {
          selector: "edge[attribute_type = 'guardian_phone']",
          style: { "line-color": CONTACT_COLOUR, width: 1.6, opacity: 0.55 },
        },
        {
          selector: ":selected",
          style: { "border-width": 3, "border-color": "#dc2626" },
        },
      ],
      layout: {
        name: "cose",
        animate: false,
        nodeRepulsion: () => 9000,
        idealEdgeLength: () => 70,
        padding: 28,
        randomize: false,
      } as cytoscape.LayoutOptions,
      minZoom: 0.3,
      maxZoom: 2.5,
      wheelSensitivity: 0.2,
    });

    core.on("tap", "node[type = 'student']", (event) => {
      onSelectStudent?.(event.target.data() as GraphNode["data"]);
    });
    core.on("tap", (event) => {
      if (event.target === core) onSelectStudent?.(null);
    });

    instance.current = core;
    return () => {
      core.destroy();
      instance.current = null;
    };
  }, [cluster, colours, onSelectStudent]);

  return (
    <div
      ref={container}
      style={{ height }}
      className={cn("w-full min-w-0 rounded-md border border-border bg-slate-50", className)}
    />
  );
}

/** The graph's key, kept outside the canvas so it never overlaps a node. */
export function ClusterLegend({ cluster }: { cluster: ClusterDetail }) {
  const colours = institutionColours(cluster.nodes);
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
      <span className="inline-flex items-center gap-2">
        <span
          className="h-3 w-3 rotate-45"
          style={{ background: CONTACT_COLOUR }}
          aria-hidden
        />
        <span className="text-muted-foreground">Shared contact</span>
      </span>
      {Array.from(colours.entries()).map(([name, colour]) => (
        <span key={name} className="inline-flex min-w-0 items-center gap-2">
          <span className="h-3 w-3 shrink-0 rounded-full" style={{ background: colour }} aria-hidden />
          <span className="min-w-0 text-muted-foreground">{name}</span>
        </span>
      ))}
      <span className="text-muted-foreground">
        Drag to pan, scroll to zoom, select a student for their masked detail.
      </span>
    </div>
  );
}
