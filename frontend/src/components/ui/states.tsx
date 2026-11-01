import * as React from "react";

import { AlertTriangle, Inbox, RefreshCw, SearchX, WifiOff } from "lucide-react";

import { ApiError, NetworkError } from "@/lib/api";
import { cn } from "@/lib/utils";

import { Button, Card } from "./primitives";

/**
 * Loading, empty and error states.
 *
 * Every page in COMPASS ships all three. The defaults here are deliberately opinionated:
 *
 * * Skeletons match the geometry of the content they replace. A centred spinner tells the
 *   user nothing about what is coming and makes the layout jump when it arrives.
 * * An empty state explains what would appear and offers the action that creates the
 *   first one. "No data" is a dead end.
 * * An error state says what failed, why, and gives one recovery action. A bare
 *   "Something went wrong" is the most common way to make a working product feel broken.
 */

// =====================================================================================
// Skeletons
// =====================================================================================

export function Skeleton({
  className,
  rounded = "md",
}: {
  className?: string;
  rounded?: "sm" | "md" | "lg" | "full";
}) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "skeleton",
        rounded === "sm" && "rounded-sm",
        rounded === "md" && "rounded-md",
        rounded === "lg" && "rounded-lg",
        rounded === "full" && "rounded-full",
        className,
      )}
    />
  );
}

export function SkeletonText({
  lines = 3,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton
          key={index}
          className={cn("h-3.5", index === lines - 1 ? "w-[62%]" : "w-full")}
        />
      ))}
    </div>
  );
}

export function SkeletonCard({ className }: { className?: string }) {
  return (
    <Card className={cn("space-y-4", className)}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1 space-y-2">
          <Skeleton className="h-4 w-2/5" />
          <Skeleton className="h-3 w-3/5" />
        </div>
        <Skeleton className="h-6 w-16" rounded="full" />
      </div>
      <SkeletonText lines={2} />
    </Card>
  );
}

/** Skeleton rows matching the table layout, so the header does not shift. */
export function SkeletonTable({
  rows = 5,
  columns = 4,
  className,
}: {
  rows?: number;
  columns?: number;
  className?: string;
}) {
  return (
    <div
      className={cn("overflow-hidden rounded-lg border border-border", className)}
      role="status"
      aria-label="Loading results"
    >
      <div className="flex gap-4 border-b border-border bg-surface-sunken px-4 py-3">
        {Array.from({ length: columns }).map((_, index) => (
          <Skeleton key={index} className="h-3 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div
          key={rowIndex}
          className="flex gap-4 border-b border-border px-4 py-3.5 last:border-0"
        >
          {Array.from({ length: columns }).map((_, columnIndex) => (
            <Skeleton
              key={columnIndex}
              className={cn("h-3.5 flex-1", columnIndex === 0 && "max-w-[40%]")}
            />
          ))}
        </div>
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  );
}

export function SkeletonMetricRow({ count = 4 }: { count?: number }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: count }).map((_, index) => (
        <Card key={index} className="space-y-3">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-3 w-full" />
        </Card>
      ))}
    </div>
  );
}

/**
 * A page-level loading state.
 *
 * `role="status"` with `aria-live="polite"` so a screen reader is told the page is
 * working, rather than being met with silence.
 */
export function LoadingState({
  label = "Loading",
  className,
  children,
}: {
  label?: string;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <div role="status" aria-live="polite" className={cn("space-y-4", className)}>
      <span className="sr-only">{label}…</span>
      {children ?? <SkeletonText lines={4} />}
    </div>
  );
}

// =====================================================================================
// Empty state
// =====================================================================================

export function EmptyState({
  icon,
  title,
  description,
  action,
  secondaryAction,
  className,
  tone = "default",
}: {
  icon?: React.ReactNode;
  title: string;
  /** What would appear here, and why it is empty. Not "no results". */
  description: React.ReactNode;
  action?: React.ReactNode;
  secondaryAction?: React.ReactNode;
  className?: string;
  tone?: "default" | "search" | "positive";
}) {
  const defaultIcon =
    tone === "search" ? <SearchX /> : tone === "positive" ? null : <Inbox />;

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed",
        "border-border-strong bg-surface-sunken/60 px-6 py-14 text-center",
        className,
      )}
    >
      {(icon ?? defaultIcon) && (
        <div
          aria-hidden="true"
          className={cn(
            "mb-4 grid size-11 place-items-center rounded-full",
            tone === "positive"
              ? "bg-positive-soft text-positive"
              : "bg-surface-inset text-ink-subtle",
            "[&>svg]:size-5",
          )}
        >
          {icon ?? defaultIcon}
        </div>
      )}
      <h3 className="text-h3 text-ink">{title}</h3>
      <div className="mt-2 max-w-md text-small text-ink-muted">{description}</div>
      {(action ?? secondaryAction) && (
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          {action}
          {secondaryAction}
        </div>
      )}
    </div>
  );
}

// =====================================================================================
// Error state
// =====================================================================================

/**
 * Turn an error into something a person can act on.
 *
 * The backend's stable error `code` is the switch, so the copy can be specific without
 * parsing prose — which is the whole reason the API has a code field.
 */
function describeError(error: ApiError | NetworkError | Error): {
  title: string;
  detail: string;
  recoverable: boolean;
  icon: React.ReactNode;
} {
  if (error instanceof NetworkError) {
    return {
      title: "Cannot reach the COMPASS API",
      detail: error.message,
      recoverable: true,
      icon: <WifiOff />,
    };
  }

  if (error instanceof ApiError) {
    switch (error.code) {
      case "not_authenticated":
      case "authentication_failed":
        return {
          title: "Your session has expired",
          detail: "Sign in again to continue.",
          recoverable: false,
          icon: <AlertTriangle />,
        };
      case "permission_denied":
        return {
          title: "You do not have access to this",
          detail:
            error.message ||
            "Your role does not permit this view. If you think it should, ask an " +
              "administrator of your organization.",
          recoverable: false,
          icon: <AlertTriangle />,
        };
      case "not_found":
        return {
          title: "Not found",
          detail:
            "This item either does not exist or belongs to another organization. " +
            "Check the link you followed.",
          recoverable: false,
          icon: <SearchX />,
        };
      case "approval_required":
        return {
          title: "Approval required",
          detail: error.message,
          recoverable: false,
          icon: <AlertTriangle />,
        };
      case "throttled": {
        const retry = error.details.retry_after_seconds;
        return {
          title: "Too many requests",
          detail: retry
            ? `Rate limit reached. Try again in about ${retry} seconds.`
            : "Rate limit reached. Wait a moment and try again.",
          recoverable: true,
          icon: <AlertTriangle />,
        };
      }
      case "integration_not_configured":
      case "integration_unavailable":
        return {
          title: "Integration unavailable",
          detail: error.message,
          recoverable: true,
          icon: <AlertTriangle />,
        };
      case "internal_error":
        return {
          title: "Something went wrong on our side",
          detail:
            error.details.incident_id
              ? `This has been logged with reference ${String(error.details.incident_id)}. ` +
                "Trying again often works."
              : "This has been logged. Trying again often works.",
          recoverable: true,
          icon: <AlertTriangle />,
        };
      default:
        return {
          title: "That did not work",
          detail: error.message,
          recoverable: true,
          icon: <AlertTriangle />,
        };
    }
  }

  return {
    title: "Something went wrong",
    detail: error.message || "An unexpected error occurred.",
    recoverable: true,
    icon: <AlertTriangle />,
  };
}

export function ErrorState({
  error,
  onRetry,
  className,
  compact,
}: {
  error: ApiError | NetworkError | Error;
  onRetry?: () => void;
  className?: string;
  compact?: boolean;
}) {
  const { title, detail, recoverable, icon } = describeError(error);

  if (compact) {
    return (
      <div
        role="alert"
        className={cn(
          "flex items-start gap-2.5 rounded-md border border-critical/25",
          "bg-critical-soft px-3.5 py-3",
          className,
        )}
      >
        <span aria-hidden="true" className="mt-0.5 shrink-0 text-critical [&>svg]:size-4">
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-small font-medium text-ink">{title}</p>
          <p className="mt-0.5 text-small text-ink-muted">{detail}</p>
        </div>
        {recoverable && onRetry && (
          <Button size="sm" variant="ghost" onClick={onRetry} icon={<RefreshCw />}>
            Retry
          </Button>
        )}
      </div>
    );
  }

  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border",
        "border-critical/20 bg-critical-soft px-6 py-12 text-center",
        className,
      )}
    >
      <div
        aria-hidden="true"
        className="mb-4 grid size-11 place-items-center rounded-full bg-critical/10 text-critical [&>svg]:size-5"
      >
        {icon}
      </div>
      <h3 className="text-h3 text-ink">{title}</h3>
      <p className="mt-2 max-w-md text-small text-ink-muted">{detail}</p>
      {recoverable && onRetry && (
        <Button variant="secondary" onClick={onRetry} icon={<RefreshCw />} className="mt-5">
          Try again
        </Button>
      )}
    </div>
  );
}

/** Inline error for form submissions, below the fields and above the submit button. */
export function FormError({
  error,
  className,
}: {
  error: ApiError | NetworkError | Error | null;
  className?: string;
}) {
  if (!error) return null;
  const { title, detail } = describeError(error);
  return (
    <div
      role="alert"
      className={cn(
        "rounded-md border border-critical/25 bg-critical-soft px-3.5 py-3",
        className,
      )}
    >
      <p className="text-small font-medium text-ink">{title}</p>
      <p className="mt-0.5 text-small text-ink-muted">{detail}</p>
    </div>
  );
}

/**
 * A region that resolves loading, error, empty and content in one place.
 *
 * Every list and detail view uses this, which is how all four states end up guaranteed
 * rather than remembered.
 */
export function AsyncRegion<T>({
  loading,
  error,
  data,
  onRetry,
  skeleton,
  empty,
  isEmpty,
  children,
}: {
  loading: boolean;
  error: ApiError | NetworkError | null;
  data: T | null;
  onRetry?: () => void;
  skeleton?: React.ReactNode;
  empty?: React.ReactNode;
  isEmpty?: (data: T) => boolean;
  children: (data: T) => React.ReactNode;
}) {
  if (loading && data === null) {
    return <LoadingState>{skeleton}</LoadingState>;
  }
  if (error && data === null) {
    return <ErrorState error={error} onRetry={onRetry} />;
  }
  if (data === null) {
    return empty ? <>{empty}</> : null;
  }
  if (isEmpty?.(data) && empty) {
    return <>{empty}</>;
  }
  return (
    <>
      {/* A refetch keeps the previous content visible and marks the region busy. */}
      {error && <ErrorState error={error} onRetry={onRetry} compact className="mb-4" />}
      <div aria-busy={loading || undefined} className={loading ? "opacity-70" : undefined}>
        {children(data)}
      </div>
    </>
  );
}
