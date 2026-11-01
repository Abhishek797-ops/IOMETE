"use client";

import * as React from "react";

import { ChevronRight, Minus, TrendingDown, TrendingUp } from "lucide-react";

import type { Metric } from "@/lib/types";
import { useLocalPreference } from "@/lib/hooks";
import { cn, confidenceBand, number as formatNumber, percent } from "@/lib/utils";

import { Badge, Card, Eyebrow, type BadgeTone } from "./primitives";
import { ConfidenceBadge } from "./trust";

// =====================================================================================
// Table
// =====================================================================================

export interface Column<T> {
  key: string;
  header: React.ReactNode;
  /** Rendered in the cell. */
  cell: (row: T) => React.ReactNode;
  /** Shown instead of the cell on narrow screens, where the table collapses to cards. */
  mobileLabel?: string;
  align?: "left" | "right" | "center";
  width?: string;
  numeric?: boolean;
  /** Columns marked secondary are hidden in the mobile card layout. */
  secondary?: boolean;
}

/**
 * A data table that collapses to a definition list on narrow screens.
 *
 * Horizontal scrolling a six-column table on a phone is technically responsive and
 * practically unusable, so below `md` each row becomes a card of label/value pairs. The
 * scrollable variant is kept for genuinely wide numeric tables, where it is marked as a
 * labelled scroll region.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  caption,
  className,
  layout = "collapse",
  emptyMessage,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  caption: string;
  className?: string;
  layout?: "collapse" | "scroll";
  emptyMessage?: React.ReactNode;
}) {
  if (rows.length === 0 && emptyMessage) {
    return <>{emptyMessage}</>;
  }

  const table = (
    <table className="w-full border-collapse text-small">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="border-b border-border bg-surface-sunken">
          {columns.map((column) => (
            <th
              key={column.key}
              scope="col"
              style={column.width ? { width: column.width } : undefined}
              className={cn(
                "px-4 py-2.5 text-micro font-semibold uppercase text-ink-subtle",
                column.align === "right" && "text-right",
                column.align === "center" && "text-center",
                !column.align && "text-left",
              )}
            >
              {column.header}
            </th>
          ))}
          {onRowClick && <th scope="col" className="w-10 px-2" />}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={rowKey(row)}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
            className={cn(
              "border-b border-border last:border-0",
              onRowClick && "cursor-pointer transition-colors hover:bg-surface-sunken",
            )}
          >
            {columns.map((column) => (
              <td
                key={column.key}
                className={cn(
                  "px-4 py-3 align-middle text-ink",
                  column.align === "right" && "text-right",
                  column.align === "center" && "text-center",
                  column.numeric && "tabular",
                )}
              >
                {column.cell(row)}
              </td>
            ))}
            {onRowClick && (
              <td className="px-2 text-ink-subtle">
                <ChevronRight aria-hidden="true" className="size-4" />
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <div className={className}>
      {/* Desktop and tablet */}
      <div
        className={cn(
          "overflow-hidden rounded-lg border border-border bg-surface-raised",
          layout === "collapse" ? "hidden md:block" : "block",
        )}
      >
        {layout === "scroll" ? (
          <div
            role="region"
            aria-label={`${caption} (scrollable)`}
            tabIndex={0}
            className="overflow-x-auto"
          >
            {table}
          </div>
        ) : (
          table
        )}
      </div>

      {/* Mobile: one card per row */}
      {layout === "collapse" && (
        <ul className="space-y-2.5 md:hidden">
          {rows.map((row) => {
            const primary = columns[0];
            return (
              <li key={rowKey(row)}>
                <Card
                  tone="raised"
                  padded={false}
                  interactive={Boolean(onRowClick)}
                  className="p-4"
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                >
                  {primary && (
                    <div className="mb-3 text-small font-medium text-ink">
                      {primary.cell(row)}
                    </div>
                  )}
                  <dl className="space-y-1.5">
                    {columns
                      .slice(1)
                      .filter((column) => !column.secondary)
                      .map((column) => (
                        <div key={column.key} className="flex items-start justify-between gap-3">
                          <dt className="text-small text-ink-subtle">
                            {column.mobileLabel ?? column.key}
                          </dt>
                          <dd
                            className={cn(
                              "min-w-0 text-right text-small text-ink",
                              column.numeric && "tabular",
                            )}
                          >
                            {column.cell(row)}
                          </dd>
                        </div>
                      ))}
                  </dl>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// =====================================================================================
// Tabs
// =====================================================================================

export interface TabItem {
  id: string;
  label: React.ReactNode;
  count?: number;
  icon?: React.ReactNode;
}

/**
 * An accessible tab list.
 *
 * Implements the ARIA tabs pattern properly, including arrow-key navigation — a row of
 * buttons that merely looks like tabs is a keyboard trap for anyone not using a mouse.
 * `persistKey` remembers the selection per viewer, which is the sort of thing
 * `localStorage` is genuinely for.
 */
export function Tabs({
  items,
  value,
  onChange,
  persistKey,
  className,
  children,
}: {
  items: TabItem[];
  value?: string;
  onChange?: (id: string) => void;
  persistKey?: string;
  className?: string;
  children?: (activeId: string) => React.ReactNode;
}) {
  const fallback = items[0]?.id ?? "";
  const [stored, setStored] = useLocalPreference(persistKey ?? "tabs.unnamed", fallback);
  const controlled = value !== undefined;
  const active = controlled ? value : (items.some((i) => i.id === stored) ? stored : fallback);
  const listId = React.useId();

  const select = (id: string) => {
    if (!controlled && persistKey) setStored(id);
    else if (!controlled) setStored(id);
    onChange?.(id);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const index = items.findIndex((item) => item.id === active);
    if (index < 0) return;
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % items.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + items.length) % items.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = items.length - 1;
    else return;
    event.preventDefault();
    const target = items[next];
    if (target) {
      select(target.id);
      document.getElementById(`${listId}-tab-${target.id}`)?.focus();
    }
  };

  return (
    <div className={className}>
      <div
        role="tablist"
        aria-orientation="horizontal"
        onKeyDown={onKeyDown}
        className="scroll-fade-r -mb-px flex gap-1 overflow-x-auto border-b border-border"
      >
        {items.map((item) => {
          const selected = item.id === active;
          return (
            <button
              key={item.id}
              id={`${listId}-tab-${item.id}`}
              role="tab"
              type="button"
              aria-selected={selected}
              aria-controls={`${listId}-panel-${item.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => select(item.id)}
              className={cn(
                "relative flex shrink-0 items-center gap-2 whitespace-nowrap px-3.5 py-2.5",
                "text-small font-medium transition-colors",
                selected
                  ? "text-ink after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:bg-accent-500"
                  : "text-ink-muted hover:text-ink",
              )}
            >
              {item.icon && <span className="[&>svg]:size-4">{item.icon}</span>}
              {item.label}
              {item.count !== undefined && (
                <span
                  className={cn(
                    "rounded-full px-1.5 py-0.5 text-[11px] tabular",
                    selected ? "bg-accent-100 text-accent-800 dark:text-accent-200" : "bg-surface-inset text-ink-subtle",
                  )}
                >
                  {item.count}
                </span>
              )}
            </button>
          );
        })}
      </div>
      {children && (
        <div
          id={`${listId}-panel-${active}`}
          role="tabpanel"
          aria-labelledby={`${listId}-tab-${active}`}
          tabIndex={0}
          className="pt-5 focus-visible:outline-none"
        >
          {children(active)}
        </div>
      )}
    </div>
  );
}

// =====================================================================================
// Scores
// =====================================================================================

const SCORE_TONES: Record<string, string> = {
  strong: "bg-positive",
  moderate: "bg-info",
  weak: "bg-caution",
  negligible: "bg-ink-subtle",
};

/**
 * A single confidence score with its label and meaning.
 *
 * The explanation is not optional: a bar labelled "Diagnosis 67%" with no statement of
 * what that measures is exactly the kind of number people misread.
 */
export function ConfidenceMeter({
  label,
  value,
  explanation,
  className,
  compact,
}: {
  label: string;
  value: number;
  explanation?: string;
  className?: string;
  compact?: boolean;
}) {
  const band = confidenceBand(value);
  const descriptionId = React.useId();

  return (
    <div className={cn("min-w-0", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <span className={cn("text-ink-muted", compact ? "text-[11px]" : "text-small")}>
          {label}
        </span>
        <span
          className={cn("font-semibold tabular text-ink", compact ? "text-small" : "text-body")}
        >
          {percent(value)}
        </span>
      </div>
      <div
        role="meter"
        aria-valuenow={Math.round(value * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label}: ${percent(value)}, ${band.label}`}
        aria-describedby={explanation ? descriptionId : undefined}
        className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-inset"
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-500", SCORE_TONES[band.tone])}
          style={{ width: `${Math.max(2, Math.round(value * 100))}%` }}
        />
      </div>
      {explanation && (
        <p id={descriptionId} className="mt-1.5 text-[11px] leading-snug text-ink-subtle">
          {explanation}
        </p>
      )}
    </div>
  );
}

/**
 * The three scores, side by side and never merged.
 *
 * This component exists specifically to make the distinction impossible to miss. Each
 * score carries the backend's own explanation of what it measures, so a reader can see
 * that "looks very similar" and "fix will work here" are different claims.
 */
export function ScoreTrio({
  similarity,
  diagnosis,
  resolution,
  explanations,
  className,
  compact,
}: {
  similarity: number;
  diagnosis: number;
  resolution: number;
  explanations?: {
    similarity_score: string;
    diagnosis_confidence: string;
    resolution_confidence: string;
  };
  className?: string;
  compact?: boolean;
}) {
  return (
    <div className={cn("grid gap-4 sm:grid-cols-3", className)}>
      <ConfidenceMeter
        label="Similarity"
        value={similarity}
        explanation={explanations?.similarity_score}
        compact={compact}
      />
      <ConfidenceMeter
        label="Diagnosis confidence"
        value={diagnosis}
        explanation={explanations?.diagnosis_confidence}
        compact={compact}
      />
      <ConfidenceMeter
        label="Resolution confidence"
        value={resolution}
        explanation={explanations?.resolution_confidence}
        compact={compact}
      />
    </div>
  );
}

/** Horizontal progress, for a rubric dimension or a funnel stage. */
export function ProgressBar({
  value,
  max,
  tone = "accent",
  label,
  className,
}: {
  value: number;
  max: number;
  tone?: BadgeTone;
  label?: string;
  className?: string;
}) {
  const ratio = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  const fills: Partial<Record<BadgeTone, string>> = {
    accent: "bg-accent-500",
    positive: "bg-positive",
    caution: "bg-caution",
    critical: "bg-critical",
    info: "bg-info",
    neutral: "bg-ink-subtle",
  };
  return (
    <div
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-label={label}
      className={cn("h-2 w-full overflow-hidden rounded-full bg-surface-inset", className)}
    >
      <div
        className={cn("h-full rounded-full transition-[width] duration-500", fills[tone] ?? fills.accent)}
        style={{ width: `${Math.max(ratio > 0 ? 2 : 0, ratio * 100)}%` }}
      />
    </div>
  );
}

// =====================================================================================
// Metrics
// =====================================================================================

/**
 * A metric tile that tells the truth about its own number.
 *
 * Renders the value, how it was derived (`basis`), its sample size, and its confidence. A
 * null value with `insufficient_data` shows "Not enough data" rather than a zero — which
 * is the specific thing the brief forbids and the most common way dashboards mislead.
 */
export function MetricTile({
  metric,
  className,
  emphasis,
}: {
  metric: Metric;
  className?: string;
  emphasis?: boolean;
}) {
  const insufficient = metric.confidence === "insufficient_data" || metric.value === null;
  const detailsId = React.useId();

  const display = (() => {
    if (insufficient) return "—";
    if (typeof metric.value === "number") {
      if (metric.unit === "ratio") return percent(metric.value);
      if (metric.unit === "hours") return `${metric.value}h`;
      return formatNumber(metric.value);
    }
    return "—";
  })();

  const comparison =
    metric.value && typeof metric.value === "object"
      ? (metric.value as Record<string, number | null>)
      : null;

  return (
    <Card
      tone={emphasis ? "raised" : "flat"}
      className={cn("flex flex-col gap-2", emphasis && "border-accent-200", className)}
    >
      <div className="flex items-start justify-between gap-3">
        <Eyebrow className="min-w-0">{metric.label}</Eyebrow>
        {metric.confidence !== "measured" && (
          <ConfidenceBadge confidence={metric.confidence} />
        )}
      </div>

      {comparison ? (
        <dl className="space-y-1.5">
          {Object.entries(comparison).map(([key, value]) => (
            <div key={key} className="flex items-baseline justify-between gap-3">
              <dt className="text-small text-ink-muted">
                {key.replace(/_/g, " ").replace(/\bhours\b/, "")}
              </dt>
              <dd className="text-h3 tabular text-ink">
                {value === null ? "—" : `${value}h`}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p
          className={cn(
            "tabular font-semibold text-ink",
            emphasis ? "text-[2rem] leading-none" : "text-h2",
          )}
          aria-describedby={detailsId}
        >
          {display}
          {!insufficient && metric.unit && !["ratio", "hours"].includes(metric.unit) && (
            <span className="ml-1.5 text-small font-normal text-ink-subtle">
              {metric.unit}
            </span>
          )}
        </p>
      )}

      <div id={detailsId} className="space-y-1.5">
        {insufficient ? (
          <p className="text-small text-ink-muted">
            {metric.caveat || "Not enough data to report this yet."}
          </p>
        ) : (
          <p className="text-[11px] leading-snug text-ink-subtle">{metric.basis}</p>
        )}
        {!insufficient && metric.caveat && (
          <p className="text-[11px] leading-snug text-caution">{metric.caveat}</p>
        )}
        <p className="text-[11px] text-ink-subtle">
          {metric.window}
          {metric.sample_size > 0 && ` · from ${formatNumber(metric.sample_size)} records`}
        </p>
      </div>
    </Card>
  );
}

/** A compact counter for a dashboard strip. */
export function StatTile({
  label,
  value,
  hint,
  tone = "neutral",
  trend,
  href,
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: BadgeTone;
  trend?: { direction: "up" | "down" | "flat"; label: string };
  href?: string;
  className?: string;
}) {
  const accents: Partial<Record<BadgeTone, string>> = {
    critical: "border-l-critical",
    caution: "border-l-caution",
    positive: "border-l-positive",
    info: "border-l-info",
    accent: "border-l-accent-500",
    neutral: "border-l-border-strong",
  };

  const body = (
    <>
      <Eyebrow>{label}</Eyebrow>
      <p className="mt-1.5 text-h2 tabular font-semibold text-ink">{value}</p>
      {trend && (
        <p className="mt-1 flex items-center gap-1 text-small text-ink-muted">
          {trend.direction === "up" && (
            <TrendingUp aria-hidden="true" className="size-3.5 text-positive" />
          )}
          {trend.direction === "down" && (
            <TrendingDown aria-hidden="true" className="size-3.5 text-critical" />
          )}
          {trend.direction === "flat" && (
            <Minus aria-hidden="true" className="size-3.5 text-ink-subtle" />
          )}
          {trend.label}
        </p>
      )}
      {hint && <p className="mt-1.5 text-[11px] leading-snug text-ink-subtle">{hint}</p>}
    </>
  );

  const classes = cn(
    "block rounded-lg border border-l-2 border-border bg-surface-raised p-4",
    accents[tone] ?? accents.neutral,
    href && "transition-colors hover:bg-surface-sunken",
    className,
  );

  if (href) {
    return (
      <a href={href} className={classes}>
        {body}
      </a>
    );
  }
  return <div className={classes}>{body}</div>;
}

/**
 * A key/value row list, for showing retrieval internals.
 *
 * Used to disclose which channels fired and which vector backend answered — information
 * the product reports on principle rather than hiding.
 */
export function KeyValueGrid({
  entries,
  className,
  columns = 2,
}: {
  entries: { label: string; value: React.ReactNode; hint?: string }[];
  className?: string;
  columns?: 2 | 3 | 4;
}) {
  return (
    <dl
      className={cn(
        "grid gap-x-6 gap-y-3",
        columns === 2 && "sm:grid-cols-2",
        columns === 3 && "sm:grid-cols-3",
        columns === 4 && "sm:grid-cols-2 lg:grid-cols-4",
        className,
      )}
    >
      {entries.map((entry) => (
        <div key={entry.label} className="min-w-0">
          <dt className="text-[11px] uppercase tracking-wide text-ink-subtle">
            {entry.label}
          </dt>
          <dd className="mt-0.5 text-small tabular text-ink">{entry.value}</dd>
          {entry.hint && (
            <dd className="mt-0.5 text-[11px] leading-snug text-ink-subtle">{entry.hint}</dd>
          )}
        </div>
      ))}
    </dl>
  );
}

/** Retrieval-channel contributions, as a labelled bar set. */
export function ChannelBars({
  scores,
  weights,
  className,
}: {
  scores: Record<string, number>;
  weights?: Record<string, number>;
  className?: string;
}) {
  const channels = ["vector", "lexical", "fingerprint", "metadata"];
  const labels: Record<string, string> = {
    vector: "Semantic",
    lexical: "Keyword",
    fingerprint: "Error signature",
    metadata: "Metadata",
  };

  return (
    <div className={cn("space-y-2", className)}>
      {channels.map((channel) => {
        const score = scores[channel] ?? 0;
        const contributed = score > 0;
        return (
          <div key={channel} className="flex items-center gap-3">
            <span className="w-28 shrink-0 text-[11px] text-ink-subtle">
              {labels[channel] ?? channel}
            </span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-inset">
              <div
                className={cn(
                  "h-full rounded-full",
                  channel === "fingerprint" ? "bg-accent-500" : "bg-info",
                )}
                style={{ width: `${Math.round(Math.min(1, score) * 100)}%` }}
              />
            </div>
            <span className="w-10 shrink-0 text-right text-[11px] tabular text-ink-muted">
              {contributed ? score.toFixed(2) : "—"}
            </span>
            {weights?.[channel] !== undefined && (
              <span className="w-12 shrink-0 text-right text-[11px] tabular text-ink-subtle">
                ×{weights[channel]}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** A horizontal funnel, for the knowledge-compounding lifecycle. */
export function Funnel({
  stages,
  className,
}: {
  stages: { key: string; label: string; count: number; description: string }[];
  className?: string;
}) {
  const peak = Math.max(...stages.map((stage) => stage.count), 1);
  return (
    <ol className={cn("space-y-3", className)}>
      {stages.map((stage, index) => {
        const ratio = stage.count / peak;
        const isLast = index === stages.length - 1;
        return (
          <li key={stage.key}>
            <div className="flex items-baseline justify-between gap-3">
              <span
                className={cn(
                  "text-small font-medium",
                  isLast ? "text-accent-700 dark:text-accent-300" : "text-ink",
                )}
              >
                {stage.label}
              </span>
              <span className="text-body tabular font-semibold text-ink">
                {formatNumber(stage.count)}
              </span>
            </div>
            <div className="mt-1.5 h-2.5 w-full overflow-hidden rounded-full bg-surface-inset">
              <div
                className={cn(
                  "h-full rounded-full transition-[width] duration-700",
                  isLast ? "bg-accent-500" : "bg-info/70",
                )}
                style={{ width: `${Math.max(ratio > 0 ? 2 : 0, ratio * 100)}%` }}
              />
            </div>
            <p className="mt-1 text-[11px] leading-snug text-ink-subtle">{stage.description}</p>
          </li>
        );
      })}
    </ol>
  );
}

/** A count badge for a bucket header. */
export function CountPill({
  count,
  tone = "neutral",
}: {
  count: number;
  tone?: BadgeTone;
}) {
  return (
    <Badge tone={tone} size="sm" className="tabular">
      {formatNumber(count)}
    </Badge>
  );
}
