"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Shared chart furniture.
 *
 * Every chart in COMPASS draws from the same six-slot categorical palette, assigned in
 * a fixed order and never cycled. The order is the colour-blindness safety mechanism:
 * the light and dark sets were both validated for OKLCH lightness band, chroma floor,
 * protan/deutan separation, the normal-vision floor and ≥3:1 contrast against the chart
 * surface. Adding a seventh hue by hand would silently break that, so `seriesColor`
 * wraps round the six and the callers fold anything beyond into "Other".
 */
export const CHART_SERIES = [
  "var(--color-chart-1)",
  "var(--color-chart-2)",
  "var(--color-chart-3)",
  "var(--color-chart-4)",
  "var(--color-chart-5)",
  "var(--color-chart-6)",
] as const;

/** One hue, light → dark. For magnitude and for ordinal sequences like funnel stages. */
export const CHART_SEQUENTIAL = [
  "var(--color-chart-seq-1)",
  "var(--color-chart-seq-2)",
  "var(--color-chart-seq-3)",
  "var(--color-chart-seq-4)",
  "var(--color-chart-seq-5)",
] as const;

export const CHART_MAX_SERIES = CHART_SERIES.length;

/** Colour for series `index`. Identity follows the entity, never its rank. */
export function seriesColor(index: number): string {
  return CHART_SERIES[index % CHART_SERIES.length]!;
}

/**
 * A step from the sequential ramp for position `index` of `count`.
 *
 * Used for ordinal data — funnel stages, tiers, buckets — where the reader should see
 * the order in the colour rather than guess it from a legend.
 */
export function sequentialStep(index: number, count: number): string {
  if (count <= 1) return CHART_SEQUENTIAL[3]!;
  const ratio = index / (count - 1);
  const step = Math.round(ratio * (CHART_SEQUENTIAL.length - 1));
  return CHART_SEQUENTIAL[step]!;
}

export const GRID_COLOR = "var(--color-chart-grid)";
export const AXIS_COLOR = "var(--color-chart-axis)";
export const SURFACE_COLOR = "var(--color-chart-surface)";

/** Recharts axis styling, kept recessive and identical across every chart. */
export const AXIS_PROPS = {
  stroke: AXIS_COLOR,
  tick: { fill: AXIS_COLOR, fontSize: 11 },
  tickLine: false,
  axisLine: false,
} as const;

/**
 * A chart frame: title, optional note, the plot, and a legend.
 *
 * Takes `caption` rather than leaving the explanation to a tooltip, and `source` so a
 * chart built from synthetic or simulated data says so on its face. A chart in COMPASS
 * that does not state where its numbers came from is a bug.
 */
export function ChartFrame({
  title,
  subtitle,
  note,
  action,
  children,
  className,
  height = 280,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  note?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  height?: number;
}) {
  return (
    <figure className={cn("min-w-0", className)}>
      {(title || action) && (
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {title && (
              <figcaption className="text-small font-medium text-ink">{title}</figcaption>
            )}
            {subtitle && (
              <p className="mt-0.5 text-[11px] leading-snug text-ink-subtle">{subtitle}</p>
            )}
          </div>
          {action}
        </div>
      )}
      <div className="mt-3" style={{ height }}>
        {children}
      </div>
      {note && (
        <p className="mt-2.5 text-[11px] leading-snug text-ink-subtle">{note}</p>
      )}
    </figure>
  );
}

/**
 * The legend.
 *
 * Always rendered for two or more series, because colour alone is not an identity
 * channel. A single series gets none — the title already names it, and a one-swatch box
 * is furniture.
 */
export function ChartLegend({
  entries,
  className,
}: {
  entries: { label: string; color: string }[];
  className?: string;
}) {
  if (entries.length < 2) return null;
  return (
    <ul className={cn("mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5", className)}>
      {entries.map((entry) => (
        <li key={entry.label} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="size-2.5 shrink-0 rounded-[2px]"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-[11px] text-ink-muted">{entry.label}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * The tooltip body.
 *
 * Values wear text tokens; identity comes from the swatch beside them. A light
 * categorical hue used as text is illegible on the surface, which is why the series
 * colour never touches the type.
 */
export function ChartTooltip({
  label,
  rows,
}: {
  label?: React.ReactNode;
  rows: { key: string; label: string; value: React.ReactNode; color?: string }[];
}) {
  if (rows.length === 0) return null;
  return (
    <div className="pointer-events-none rounded-md border border-border bg-surface-raised px-3 py-2 shadow-float">
      {label !== undefined && label !== "" && (
        <p className="text-[11px] font-medium text-ink">{label}</p>
      )}
      <dl className="mt-1 space-y-1">
        {rows.map((row) => (
          <div key={row.key} className="flex items-center gap-2">
            {row.color && (
              <span
                aria-hidden="true"
                className="size-2 shrink-0 rounded-[2px]"
                style={{ backgroundColor: row.color }}
              />
            )}
            <dt className="text-[11px] text-ink-muted">{row.label}</dt>
            <dd className="ml-auto text-[11px] tabular font-medium text-ink">{row.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
