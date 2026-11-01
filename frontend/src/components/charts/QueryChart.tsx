"use client";

import * as React from "react";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ChartHint } from "@/lib/types";
import { cn, compactNumber, number } from "@/lib/utils";

import {
  AXIS_PROPS,
  CHART_MAX_SERIES,
  ChartFrame,
  ChartLegend,
  ChartTooltip,
  GRID_COLOR,
  SURFACE_COLOR,
  sequentialStep,
  seriesColor,
} from "./primitives";

type CellValue = string | number | null;

/** A tick formatter that switches to compact notation only once the axis needs it. */
function axisNumber(value: number, max: number): string {
  return max >= 10_000 ? compactNumber(value) : number(value);
}

function toRecords(columns: string[], rows: CellValue[][]): Record<string, CellValue>[] {
  return rows.map((row) => {
    const record: Record<string, CellValue> = {};
    columns.forEach((column, index) => {
      record[column] = row[index] ?? null;
    });
    return record;
  });
}

function asNumber(value: CellValue | undefined): number | null {
  if (value === null || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function labelOf(column: string): string {
  return column.replace(/_/g, " ").replace(/^./, (character) => character.toUpperCase());
}

/**
 * A chart for a playground query result.
 *
 * Driven by the `chart` hint the backend attaches to each sample query, so the shape of
 * the visualisation is a property of the query rather than something guessed from column
 * types. If the hint does not match the columns actually returned — which happens the
 * moment someone edits the SQL — the chart declines to render and says why, rather than
 * drawing a plausible-looking chart of the wrong thing.
 *
 * Two deliberate omissions. There is no dual-axis mode: two measures of different scale
 * become two charts stacked vertically, never two y-scales on one plot. And there is no
 * generated seventh hue: a dimension with more than six values is cut to the top six and
 * labelled as such, because a palette beyond its validated length stops being readable.
 */
export function QueryChart({
  columns,
  rows,
  chart,
  title,
  note,
  className,
}: {
  columns: string[];
  rows: CellValue[][];
  chart: ChartHint;
  title?: React.ReactNode;
  note?: React.ReactNode;
  className?: string;
}) {
  const records = React.useMemo(() => toRecords(columns, rows), [columns, rows]);

  const missing = React.useMemo(() => {
    const required = [chart.x, ...(chart.series ? [chart.series] : []), ...chart.y];
    return required.filter((column) => !columns.includes(column));
  }, [chart, columns]);

  if (rows.length === 0) {
    return (
      <p className={cn("text-small text-ink-subtle", className)}>
        The query returned no rows, so there is nothing to plot.
      </p>
    );
  }

  if (missing.length > 0) {
    return (
      <p className={cn("text-small text-ink-muted", className)}>
        No chart for this result: it does not contain{" "}
        <span className="font-medium text-ink">{missing.join(", ")}</span>. The table below
        is the complete answer — COMPASS will not guess at a chart the columns do not
        support.
      </p>
    );
  }

  if (chart.type === "funnel") {
    return (
      <FunnelChart
        records={records}
        stageKey={chart.x}
        valueKey={chart.y[0]!}
        title={title}
        note={note}
        className={className}
      />
    );
  }

  if (chart.type === "grouped_bar" && chart.series) {
    return (
      <GroupedBars
        records={records}
        xKey={chart.x}
        seriesKey={chart.series}
        valueKey={chart.y[0]!}
        title={title}
        note={note}
        className={className}
      />
    );
  }

  // One measure per plot. Several measures become several charts: a second y-axis is the
  // single most misleading thing a chart can do, so it is not available here.
  return (
    <div className={cn("space-y-7", className)}>
      {chart.y.map((measure, index) => (
        <SingleMeasure
          key={measure}
          records={records}
          xKey={chart.x}
          valueKey={measure}
          form={chart.type === "line" ? "line" : "bar"}
          title={index === 0 ? title : undefined}
          subtitle={chart.y.length > 1 ? labelOf(measure) : undefined}
          note={index === chart.y.length - 1 ? note : undefined}
        />
      ))}
    </div>
  );
}

// =====================================================================================
// Forms
// =====================================================================================

function SingleMeasure({
  records,
  xKey,
  valueKey,
  form,
  title,
  subtitle,
  note,
}: {
  records: Record<string, CellValue>[];
  xKey: string;
  valueKey: string;
  form: "line" | "bar";
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  note?: React.ReactNode;
}) {
  const data = React.useMemo(
    () =>
      records.map((record) => ({
        label: String(record[xKey] ?? ""),
        value: asNumber(record[valueKey]),
      })),
    [records, xKey, valueKey],
  );

  const max = Math.max(0, ...data.map((point) => point.value ?? 0));
  const colour = seriesColor(0);

  return (
    <ChartFrame title={title} subtitle={subtitle ?? labelOf(valueKey)} note={note}>
      <ResponsiveContainer width="100%" height="100%">
        {form === "line" ? (
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 4 }}>
            <CartesianGrid stroke={GRID_COLOR} strokeWidth={1} vertical={false} />
            <XAxis dataKey="label" {...AXIS_PROPS} interval="preserveStartEnd" />
            <YAxis
              {...AXIS_PROPS}
              width={56}
              tickFormatter={(value: number) => axisNumber(value, max)}
            />
            <Tooltip
              cursor={{ stroke: GRID_COLOR, strokeWidth: 1 }}
              content={<MeasureTooltip label={labelOf(valueKey)} colour={colour} />}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke={colour}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              // A 2px surface ring keeps a dot legible where it crosses the line, and
              // makes the hit target bigger than the mark.
              dot={{ r: 3, fill: colour, stroke: SURFACE_COLOR, strokeWidth: 2 }}
              activeDot={{ r: 5, fill: colour, stroke: SURFACE_COLOR, strokeWidth: 2 }}
              connectNulls={false}
            />
          </LineChart>
        ) : (
          <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 4 }}>
            <CartesianGrid stroke={GRID_COLOR} strokeWidth={1} vertical={false} />
            <XAxis dataKey="label" {...AXIS_PROPS} interval={0} angle={-20} dy={10} height={54} />
            <YAxis
              {...AXIS_PROPS}
              width={56}
              tickFormatter={(value: number) => axisNumber(value, max)}
            />
            <Tooltip
              cursor={{ fill: GRID_COLOR, fillOpacity: 0.35 }}
              content={<MeasureTooltip label={labelOf(valueKey)} colour={colour} />}
            />
            <Bar
              dataKey="value"
              fill={colour}
              maxBarSize={24}
              radius={[4, 4, 0, 0]}
            />
          </BarChart>
        )}
      </ResponsiveContainer>
    </ChartFrame>
  );
}

function GroupedBars({
  records,
  xKey,
  seriesKey,
  valueKey,
  title,
  note,
  className,
}: {
  records: Record<string, CellValue>[];
  xKey: string;
  seriesKey: string;
  valueKey: string;
  title?: React.ReactNode;
  note?: React.ReactNode;
  className?: string;
}) {
  const { data, series, folded } = React.useMemo(() => {
    // Rank the dimension's values by total so that, if there are more than the palette
    // can carry, the ones that get folded into "Other" are the small ones.
    const totals = new Map<string, number>();
    for (const record of records) {
      const key = String(record[seriesKey] ?? "—");
      totals.set(key, (totals.get(key) ?? 0) + (asNumber(record[valueKey]) ?? 0));
    }
    const ranked = [...totals.entries()]
      .sort(([, a], [, b]) => b - a)
      .map(([key]) => key);

    const kept = ranked.slice(0, CHART_MAX_SERIES - (ranked.length > CHART_MAX_SERIES ? 1 : 0));
    const overflow = ranked.slice(kept.length);
    const names = overflow.length > 0 ? [...kept, "Other"] : kept;

    const byX = new Map<string, Record<string, number | string>>();
    for (const record of records) {
      const x = String(record[xKey] ?? "—");
      const rawKey = String(record[seriesKey] ?? "—");
      const key = kept.includes(rawKey) ? rawKey : "Other";
      const row = byX.get(x) ?? { label: x };
      row[key] = ((row[key] as number | undefined) ?? 0) + (asNumber(record[valueKey]) ?? 0);
      byX.set(x, row);
    }

    return {
      data: [...byX.values()],
      series: names,
      folded: overflow,
    };
  }, [records, xKey, seriesKey, valueKey]);

  const max = Math.max(
    0,
    ...data.flatMap((row) =>
      series.map((name) => (typeof row[name] === "number" ? (row[name] as number) : 0)),
    ),
  );

  const legend = series.map((name, index) => ({ label: name, color: seriesColor(index) }));

  return (
    <div className={cn("min-w-0", className)}>
      <ChartFrame
        title={title}
        // When a sample query supplies its own title, the generated description would just
        // restate it. The measure name is the useful thing to say instead.
        subtitle={
          title
            ? labelOf(valueKey)
            : `${labelOf(valueKey)} by ${labelOf(xKey).toLowerCase()} and ${labelOf(
                seriesKey,
              ).toLowerCase()}`
        }
        note={
          folded.length > 0
            ? `${folded.length} smaller ${labelOf(seriesKey).toLowerCase()} values are grouped as "Other": ${folded.join(", ")}. The table has every row.`
            : note
        }
      >
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 4 }} barGap={2}>
            <CartesianGrid stroke={GRID_COLOR} strokeWidth={1} vertical={false} />
            <XAxis dataKey="label" {...AXIS_PROPS} interval={0} />
            <YAxis
              {...AXIS_PROPS}
              width={56}
              tickFormatter={(value: number) => axisNumber(value, max)}
            />
            <Tooltip
              cursor={{ fill: GRID_COLOR, fillOpacity: 0.35 }}
              content={<SeriesTooltip names={series} />}
            />
            {series.map((name, index) => (
              <Bar
                key={name}
                dataKey={name}
                fill={seriesColor(index)}
                maxBarSize={24}
                radius={[4, 4, 0, 0]}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </ChartFrame>
      <ChartLegend entries={legend} />
      {folded.length > 0 && note && (
        <p className="mt-2 text-[11px] text-ink-subtle">{note}</p>
      )}
    </div>
  );
}

/**
 * Funnel stages as horizontal bars on one hue.
 *
 * Stages are ordinal — reordering them would change the meaning — so the colour carries
 * the order via the sequential ramp rather than spending the identity channel on it. Drawn
 * as plain bars rather than a tapering funnel shape: a trapezoid encodes the value in an
 * area the reader cannot compare, which is the whole problem with funnel graphics.
 */
function FunnelChart({
  records,
  stageKey,
  valueKey,
  title,
  note,
  className,
}: {
  records: Record<string, CellValue>[];
  stageKey: string;
  valueKey: string;
  title?: React.ReactNode;
  note?: React.ReactNode;
  className?: string;
}) {
  const stages = React.useMemo(
    () =>
      records.map((record) => ({
        label: String(record[stageKey] ?? ""),
        value: asNumber(record[valueKey]) ?? 0,
      })),
    [records, stageKey, valueKey],
  );

  const first = stages[0]?.value ?? 0;
  const max = Math.max(0, ...stages.map((stage) => stage.value));

  return (
    <div className={cn("min-w-0", className)}>
      {title && <p className="text-small font-medium text-ink">{title}</p>}
      <ol className="mt-3 space-y-2.5">
        {stages.map((stage, index) => {
          const previous = stages[index - 1]?.value;
          const widthRatio = max > 0 ? stage.value / max : 0;
          const ofFirst = first > 0 ? stage.value / first : 0;
          const stepDrop =
            previous !== undefined && previous > 0 ? 1 - stage.value / previous : null;

          return (
            <li key={stage.label}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                <span className="text-small text-ink">{stage.label}</span>
                <span className="text-small tabular text-ink-muted">
                  {number(stage.value)}
                  <span className="ml-2 text-ink-subtle">
                    {Math.round(ofFirst * 100)}% of entry
                  </span>
                </span>
              </div>
              <div className="mt-1.5 flex items-center gap-3">
                <div className="h-5 flex-1 overflow-hidden rounded-sm bg-surface-inset">
                  <div
                    className="h-full rounded-sm transition-[width] duration-500"
                    style={{
                      width: `${Math.max(widthRatio > 0 ? 1 : 0, widthRatio * 100)}%`,
                      backgroundColor: sequentialStep(index, stages.length),
                    }}
                  />
                </div>
                <span className="w-24 shrink-0 text-right text-[11px] tabular text-ink-subtle">
                  {stepDrop === null
                    ? "entry stage"
                    : `−${Math.round(stepDrop * 100)}% from last`}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
      {note && <p className="mt-3 text-[11px] text-ink-subtle">{note}</p>}
    </div>
  );
}

// =====================================================================================
// Tooltips
// =====================================================================================

interface TooltipPayloadEntry {
  name?: string | number;
  value?: string | number;
  dataKey?: string | number;
  color?: string;
}

function MeasureTooltip({
  active,
  label,
  colour,
  payload,
}: {
  active?: boolean;
  label?: string;
  colour: string;
  payload?: TooltipPayloadEntry[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0];
  const axisLabel = (point as { payload?: { label?: string } })?.payload?.label;
  return (
    <ChartTooltip
      label={axisLabel}
      rows={[
        {
          key: "value",
          label: label ?? "Value",
          value: number(asNumber((point?.value as CellValue) ?? null)),
          color: colour,
        },
      ]}
    />
  );
}

function SeriesTooltip({
  active,
  label,
  names,
  payload,
}: {
  active?: boolean;
  label?: string;
  names: string[];
  payload?: TooltipPayloadEntry[];
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <ChartTooltip
      label={label}
      rows={payload.map((entry) => {
        const name = String(entry.dataKey ?? entry.name ?? "");
        return {
          key: name,
          label: name,
          value: number(asNumber((entry.value as CellValue) ?? null)),
          color: seriesColor(Math.max(0, names.indexOf(name))),
        };
      })}
    />
  );
}
