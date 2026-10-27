"use client";

/**
 * A measured frame for Recharts.
 *
 * Recharts' own ResponsiveContainer measures once on mount, which inside a CSS
 * grid can be before the track has its final width — the symptom is bars bunched
 * at the left with the axis spread across the full card. Measuring ourselves and
 * handing the chart an explicit pixel width removes that whole class of bug.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

export function ChartFrame({
  height,
  children,
  className,
}: {
  height: number;
  children: (width: number) => ReactNode;
  className?: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const node = container.current;
    if (!node) return;
    setWidth(Math.floor(node.clientWidth));
    const observer = new ResizeObserver((entries) => {
      setWidth(Math.floor(entries[0].contentRect.width));
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={container} className={cn("w-full min-w-0", className)} style={{ height }}>
      {width > 0 && children(width)}
    </div>
  );
}

/** Chart colours. Deep blue is the accent; the comparison series is neutral. */
export const CHART_COLOURS = {
  primary: "#1e40af",
  comparison: "#94a3b8",
  grid: "#e2e8f0",
  axis: "#64748b",
} as const;

export const CHART_TOOLTIP_STYLE = {
  fontSize: 12,
  borderRadius: 8,
  border: "1px solid #e2e8f0",
  boxShadow: "0 4px 12px -2px rgb(15 23 42 / 0.08)",
} as const;
