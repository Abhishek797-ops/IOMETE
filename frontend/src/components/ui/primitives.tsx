import * as React from "react";

import { cn } from "@/lib/utils";

// =====================================================================================
// Button
// =====================================================================================

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
type ButtonSize = "sm" | "md" | "lg";

const BUTTON_BASE =
  "relative inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md " +
  "font-medium transition-[background-color,border-color,color,box-shadow,transform] " +
  "duration-150 ease-[cubic-bezier(0.22,1,0.36,1)] " +
  "disabled:pointer-events-none disabled:opacity-45 " +
  // A 1px press translation reads as a physical button without being a bounce.
  "active:translate-y-px";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-accent-600 text-white shadow-subtle hover:bg-accent-700 " +
    "focus-visible:outline-accent-600 dark:bg-accent-500 dark:hover:bg-accent-400 " +
    "dark:text-graphite-950",
  secondary:
    "bg-surface-raised text-ink border border-border-strong shadow-subtle " +
    "hover:bg-surface-sunken hover:border-ink-subtle",
  ghost: "text-ink-muted hover:bg-surface-sunken hover:text-ink",
  danger:
    "bg-critical text-white shadow-subtle hover:brightness-110 focus-visible:outline-critical",
  subtle: "bg-surface-inset text-ink hover:bg-border",
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  // 36/40/44px tall. The md default clears the 24px minimum comfortably, and lg hits the
  // 44px touch target the accessibility guidance asks for on primary mobile actions.
  sm: "h-9 px-3 text-small",
  md: "h-10 px-4 text-small",
  lg: "h-11 px-5 text-body",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner and blocks interaction. The label stays, so width does not jump. */
  loading?: boolean;
  icon?: React.ReactNode;
  iconRight?: React.ReactNode;
  fullWidth?: boolean;
}

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon,
  iconRight,
  fullWidth,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        BUTTON_BASE,
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        fullWidth && "w-full",
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Spinner className="size-4 shrink-0" />
      ) : (
        icon && <span className="shrink-0 [&>svg]:size-4">{icon}</span>
      )}
      {children}
      {iconRight && !loading && (
        <span className="shrink-0 [&>svg]:size-4">{iconRight}</span>
      )}
    </button>
  );
}

export interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Required: an icon-only control is invisible to a screen reader without it. */
  label: string;
  variant?: ButtonVariant;
  size?: "sm" | "md";
}

export function IconButton({
  label,
  variant = "ghost",
  size = "md",
  className,
  children,
  type = "button",
  ...rest
}: IconButtonProps) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        BUTTON_BASE,
        BUTTON_VARIANTS[variant],
        size === "sm" ? "size-8" : "size-10",
        "px-0 [&>svg]:size-4",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn("animate-spin", className)}
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
      <path
        d="M14.5 8a6.5 6.5 0 0 0-6.5-6.5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

// =====================================================================================
// Card
// =====================================================================================

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** `flat` for cards inside cards — nesting two raised surfaces looks like a mistake. */
  tone?: "raised" | "flat" | "sunken" | "inverse";
  interactive?: boolean;
  padded?: boolean;
}

export function Card({
  tone = "raised",
  interactive,
  padded = true,
  className,
  children,
  ...rest
}: CardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border",
        tone === "raised" && "border-border bg-surface-raised shadow-subtle",
        tone === "flat" && "border-border bg-transparent",
        tone === "sunken" && "border-border bg-surface-sunken",
        tone === "inverse" &&
          "border-graphite-800 bg-graphite-900 text-ink-inverse shadow-inverse",
        interactive &&
          "transition-[border-color,box-shadow,transform] duration-200 " +
            "ease-[cubic-bezier(0.22,1,0.36,1)] hover:-translate-y-0.5 " +
            "hover:border-border-strong hover:shadow-raised",
        padded && "p-5",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  description,
  actions,
  icon,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-4", className)}>
      <div className="flex min-w-0 items-start gap-3">
        {icon && (
          <span className="mt-0.5 shrink-0 text-ink-subtle [&>svg]:size-[18px]">{icon}</span>
        )}
        <div className="min-w-0">
          <h3 className="text-h3 text-ink">{title}</h3>
          {description && (
            <p className="mt-1 text-small text-ink-muted measure">{description}</p>
          )}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

// =====================================================================================
// Badge
// =====================================================================================

export type BadgeTone =
  | "neutral"
  | "accent"
  | "positive"
  | "caution"
  | "critical"
  | "info"
  | "verified"
  | "unverified"
  | "gated"
  | "simulated";

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: "bg-surface-inset text-ink-muted border-border",
  accent: "bg-accent-50 text-accent-800 border-accent-200 dark:text-accent-200",
  positive: "bg-positive-soft text-positive border-positive/25",
  caution: "bg-caution-soft text-caution border-caution/30",
  critical: "bg-critical-soft text-critical border-critical/25",
  info: "bg-info-soft text-info border-info/25",
  verified: "bg-verified-soft text-verified border-verified/25",
  unverified: "bg-unverified-soft text-unverified border-unverified/30",
  gated: "bg-gated-soft text-gated border-gated/25",
  simulated: "bg-simulated-soft text-simulated border-simulated/25",
};

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  size?: "sm" | "md";
  icon?: React.ReactNode;
}

export function Badge({
  tone = "neutral",
  size = "md",
  icon,
  className,
  children,
  ...rest
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border font-medium",
        size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-small",
        BADGE_TONES[tone],
        className,
      )}
      {...rest}
    >
      {icon && <span className="shrink-0 [&>svg]:size-3">{icon}</span>}
      {children}
    </span>
  );
}

/**
 * A status indicator that pairs a hue with a shape.
 *
 * Colour alone never carries meaning here: a filled ring, a hollow ring and a square are
 * distinguishable without colour vision, which is what WCAG 1.4.1 asks for.
 */
export function StatusDot({
  tone,
  shape = "dot",
  label,
  className,
}: {
  tone: BadgeTone;
  shape?: "dot" | "ring" | "square";
  label?: string;
  className?: string;
}) {
  const colour: Record<BadgeTone, string> = {
    neutral: "bg-ink-subtle",
    accent: "bg-accent-500",
    positive: "bg-positive",
    caution: "bg-caution",
    critical: "bg-critical",
    info: "bg-info",
    verified: "bg-verified",
    unverified: "bg-unverified",
    gated: "bg-gated",
    simulated: "bg-simulated",
  };
  const border: Record<BadgeTone, string> = {
    neutral: "border-ink-subtle",
    accent: "border-accent-500",
    positive: "border-positive",
    caution: "border-caution",
    critical: "border-critical",
    info: "border-info",
    verified: "border-verified",
    unverified: "border-unverified",
    gated: "border-gated",
    simulated: "border-simulated",
  };

  return (
    <span
      className={cn("inline-flex items-center gap-1.5", className)}
      {...(label ? {} : { "aria-hidden": true })}
    >
      <span
        className={cn(
          "shrink-0",
          shape === "square" ? "size-2 rounded-[2px]" : "size-2 rounded-full",
          shape === "ring" ? cn("border-2 bg-transparent", border[tone]) : colour[tone],
        )}
      />
      {label && <span className="text-small text-ink-muted">{label}</span>}
    </span>
  );
}

// =====================================================================================
// Layout atoms
// =====================================================================================

export function Divider({
  className,
  label,
  orientation = "horizontal",
}: {
  className?: string;
  label?: string;
  orientation?: "horizontal" | "vertical";
}) {
  if (orientation === "vertical") {
    return <span role="separator" className={cn("w-px self-stretch bg-border", className)} />;
  }
  if (!label) {
    return <hr className={cn("border-0 border-t border-border", className)} />;
  }
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <span className="h-px flex-1 bg-border" />
      <span className="text-micro uppercase text-ink-subtle">{label}</span>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}

/** A small-caps section label. Used instead of a fourth heading level. */
export function Eyebrow({
  children,
  className,
  as: Tag = "p",
}: {
  children: React.ReactNode;
  className?: string;
  as?: "p" | "h1" | "h2" | "h3" | "h4" | "span";
}) {
  return (
    <Tag className={cn("text-micro uppercase text-ink-subtle", className)}>{children}</Tag>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded border",
        "border-border-strong bg-surface-sunken px-1.5 font-mono text-[11px] text-ink-muted",
      )}
    >
      {children}
    </kbd>
  );
}

/** Monospace inline code. */
export function Code({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <code
      className={cn(
        "rounded border border-border bg-surface-sunken px-1.5 py-0.5 font-mono text-[0.85em]",
        className,
      )}
    >
      {children}
    </code>
  );
}

export function Avatar({
  initials,
  name,
  size = "md",
  className,
}: {
  initials: string;
  name?: string;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center rounded-full",
        "bg-accent-100 font-semibold text-accent-800 dark:text-accent-200",
        size === "sm" && "size-6 text-[10px]",
        size === "md" && "size-8 text-[11px]",
        size === "lg" && "size-11 text-small",
        className,
      )}
      title={name}
      aria-hidden={!name}
      aria-label={name}
    >
      {initials}
    </span>
  );
}

/**
 * A page-level header. Used by every operator page so the chrome is identical and the
 * page content starts in the same place.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  children,
  className,
}: {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-7", className)}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          {eyebrow && <Eyebrow className="mb-2">{eyebrow}</Eyebrow>}
          <h1 className="text-h1 text-ink">{title}</h1>
          {description && (
            <p className="mt-2 text-body text-ink-muted measure">{description}</p>
          )}
        </div>
        {actions && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
        )}
      </div>
      {children && <div className="mt-5">{children}</div>}
    </header>
  );
}

/** A labelled value, for definition-style detail panels. */
export function DetailRow({
  label,
  children,
  mono,
  className,
}: {
  label: React.ReactNode;
  children: React.ReactNode;
  mono?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("grid gap-1 py-2.5 sm:grid-cols-[minmax(0,10rem)_1fr] sm:gap-4", className)}>
      <dt className="text-small text-ink-subtle">{label}</dt>
      <dd className={cn("min-w-0 text-small text-ink", mono && "font-mono text-[0.8rem]")}>
        {children}
      </dd>
    </div>
  );
}

export function DetailList({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <dl className={cn("divide-y divide-border", className)}>{children}</dl>;
}
