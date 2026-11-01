import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge class names, with later Tailwind utilities winning over earlier conflicts. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

// =====================================================================================
// Formatting
// =====================================================================================

/**
 * Format a score as a percentage.
 *
 * Deliberately rounded to whole numbers. "67%" is an honest summary of 0.6681; "66.81%"
 * implies a precision these scores do not have.
 */
export function percent(value: number | null | undefined, fallback = "—"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback;
  return `${Math.round(value * 100)}%`;
}

export function compactNumber(value: number | null | undefined, fallback = "—"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback;
  return new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 })
    .format(value);
}

export function number(value: number | null | undefined, fallback = "—"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback;
  return new Intl.NumberFormat("en-GB").format(value);
}

export function currencyish(value: number | null | undefined, fallback = "—"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback;
  return new Intl.NumberFormat("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function bytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const hours = minutes / 60;
  if (hours < 48) return `${hours.toFixed(hours < 10 ? 1 : 0)}h`;
  return `${Math.round(hours / 24)}d`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/**
 * Relative time, for timelines.
 *
 * Switches to an absolute date beyond a month: "7 weeks ago" takes more effort to place
 * than "12 Sep 2026".
 */
export function relativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";

  const seconds = (Date.now() - date.getTime()) / 1000;
  if (seconds < 45) return "just now";
  if (seconds < 90) return "a minute ago";

  const formatter = new Intl.RelativeTimeFormat("en-GB", { numeric: "auto" });
  const minutes = seconds / 60;
  if (minutes < 60) return formatter.format(-Math.round(minutes), "minute");
  const hours = minutes / 60;
  if (hours < 24) return formatter.format(-Math.round(hours), "hour");
  const days = hours / 24;
  if (days < 31) return formatter.format(-Math.round(days), "day");
  return formatDate(value);
}

// =====================================================================================
// Domain helpers
// =====================================================================================

/**
 * A qualitative band for a confidence score.
 *
 * Capped descriptions on purpose: nothing in COMPASS is "certain", so the top band reads
 * "high" rather than anything stronger.
 */
export function confidenceBand(value: number): {
  label: string;
  tone: "strong" | "moderate" | "weak" | "negligible";
} {
  if (value >= 0.7) return { label: "High", tone: "strong" };
  if (value >= 0.45) return { label: "Moderate", tone: "moderate" };
  if (value >= 0.2) return { label: "Low", tone: "weak" };
  return { label: "Very low", tone: "negligible" };
}

export function severityTone(
  severity: string,
): "critical" | "caution" | "info" | "neutral" {
  switch (severity) {
    case "critical":
      return "critical";
    case "high":
      return "caution";
    case "medium":
      return "info";
    default:
      return "neutral";
  }
}

export function statusTone(
  status: string,
): "positive" | "caution" | "critical" | "info" | "neutral" {
  switch (status) {
    case "resolved":
    case "closed":
      return "positive";
    case "escalated":
      return "critical";
    case "in_progress":
    case "triaging":
      return "info";
    case "awaiting_customer":
      return "caution";
    default:
      return "neutral";
  }
}

/** Initials for an avatar, from a full name. */
export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name.split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return `${parts[0]![0]}${parts[parts.length - 1]![0]}`.toUpperCase();
}

export function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1).trimEnd()}…`;
}

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

/**
 * A stable per-visit session key for the anonymous lakehouse playground, so a prospect's
 * query history persists within their visit without needing an account.
 *
 * `sessionStorage` rather than `localStorage`: it should not outlive the tab. Wrapped in
 * try/catch because storage throws in a private window.
 */
export function sessionKey(): string {
  if (typeof window === "undefined") return "";
  const key = "compass.session";
  try {
    const existing = window.sessionStorage.getItem(key);
    if (existing) return existing;
    const generated = `s-${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`;
    window.sessionStorage.setItem(key, generated);
    return generated;
  } catch {
    return "";
  }
}

/** Download a client-generated file without a server round trip. */
export function downloadFile(filename: string, contents: string, type = "text/plain"): void {
  const blob = new Blob([contents], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  // Revoking immediately can cancel the download in some browsers.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function groupBy<T, K extends string | number>(
  items: readonly T[],
  key: (item: T) => K,
): Record<K, T[]> {
  const out = {} as Record<K, T[]>;
  for (const item of items) {
    const group = key(item);
    (out[group] ??= []).push(item);
  }
  return out;
}
