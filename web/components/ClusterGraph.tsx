"use client";

/**
 * Cytoscape view of one cluster. Students are circles coloured by institution; shared
 * contacts are larger diamonds in the accent colour. Every label is masked, and a
 * contact is "Guardian contact #1", never a number or a hash.
 */
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { useEffect, useMemo, useRef } from "react";

import type { ClusterDetail, GraphNode } from "@/lib/types";

const INSTITUTION_COLOURS = [
  "#1d4ed8",
  "#0e7490",
  "#7c3aed",
  "#b45309",
  "#be123c",
  "#15803d",
];

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
}: {
  cluster: ClusterDetail;
  onSelectStudent?: (node: GraphNode["data"] | null) => void;
  height?: number;
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
              : "#0ea5e9",
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
            color: "#0f172a",
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
            "background-color": "#0ea5e9",
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
            "line-color": "#94a3b8",
            "curve-style": "haystack",
            opacity: 0.7,
          },
        },
        {
          selector: "edge[attribute_type = 'guardian_phone']",
          style: { "line-color": "#0ea5e9", width: 1.6 },
        },
        {
          selector: ":selected",
          style: { "border-width": 3, "border-color": "#dc2626" },
        },
      ],
      layout: {
        name: "cose",
        animate: true,
        animationDuration: 700,
        nodeRepulsion: () => 9000,
        idealEdgeLength: () => 70,
        padding: 24,
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
    <div className="space-y-2">
      <div
        ref={container}
        style={{ height }}
        className="w-full rounded-lg border border-border bg-gradient-to-b from-slate-50 to-white"
      />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-3 rotate-45 bg-sky-500" /> shared contact
        </span>
        {Array.from(colours.entries()).map(([name, colour]) => (
          <span key={name} className="inline-flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-full" style={{ background: colour }} />
            <span className="max-w-[16rem] truncate">{name}</span>
          </span>
        ))}
        <span>· drag to pan, scroll to zoom, click a student for detail</span>
      </div>
    </div>
  );
}
