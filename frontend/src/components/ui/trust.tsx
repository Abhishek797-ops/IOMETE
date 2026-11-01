import * as React from "react";

import {
  AlertTriangle,
  Archive,
  BadgeCheck,
  Ban,
  CircleHelp,
  ExternalLink,
  FileQuestion,
  FlaskConical,
  Info,
  Quote,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import type {
  ClaimStatus,
  GateStatus,
  MatchEvidence,
  MetricConfidence,
  NodeClaimStatus,
  PlaybookListItem,
  SourceRef,
} from "@/lib/types";
import { cn } from "@/lib/utils";

import { Badge, type BadgeTone, Card, Eyebrow } from "./primitives";

/**
 * Trust and provenance components.
 *
 * This file is the UI half of the product's central promise. Everything here exists so
 * that a reader can always tell:
 *
 * * whether a product claim is documented, a vendor claim, or unconfirmed;
 * * whether a playbook is verified knowledge or an unreviewed draft;
 * * whether a match is applicable to them or gated out;
 * * whether a number is measured, modelled, or absent for want of data;
 * * whether what they are looking at is synthetic demo data.
 *
 * These are not decorative badges. A draft styled like approved knowledge, or an estimate
 * presented as a measurement, is the specific failure this product is built to avoid — so
 * the styling lives in one place and every surface uses it.
 */

// =====================================================================================
// Product claim status
// =====================================================================================

const CLAIM_PRESENTATION: Record<
  ClaimStatus,
  { tone: BadgeTone; label: string; icon: React.ReactNode }
> = {
  verified: { tone: "verified", label: "Documented", icon: <BadgeCheck /> },
  vendor_claim: { tone: "caution", label: "IOMETE claim", icon: <Quote /> },
  needs_confirmation: { tone: "unverified", label: "Needs confirmation", icon: <CircleHelp /> },
  industry_concept: { tone: "info", label: "Industry concept", icon: <Info /> },
};

export function ClaimStatusBadge({
  status,
  size = "sm",
  className,
}: {
  status: ClaimStatus | undefined;
  size?: "sm" | "md";
  className?: string;
}) {
  if (!status) return null;
  const presentation = CLAIM_PRESENTATION[status];
  return (
    <Badge tone={presentation.tone} size={size} icon={presentation.icon} className={className}>
      {presentation.label}
    </Badge>
  );
}

/**
 * The status legend, rendered from what the API returns.
 *
 * Served with the data rather than hardcoded here so the UI cannot drift from the policy
 * in `docs/product-knowledge/README.md`.
 */
export function ClaimStatusLegend({
  legend,
  className,
}: {
  legend: Partial<Record<ClaimStatus, string>>;
  className?: string;
}) {
  const entries = Object.entries(legend) as [ClaimStatus, string][];
  if (entries.length === 0) return null;
  return (
    <Card tone="sunken" className={cn("space-y-3", className)}>
      <Eyebrow as="h3">How to read these labels</Eyebrow>
      <dl className="space-y-2.5">
        {entries.map(([status, meaning]) => (
          <div key={status} className="flex flex-col gap-1.5 sm:flex-row sm:gap-3">
            <dt className="shrink-0 sm:w-44">
              <ClaimStatusBadge status={status} />
            </dt>
            <dd className="text-small text-ink-muted">{meaning}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

/** Source citations, as links to the official page each claim was read from. */
export function SourceList({
  sources,
  label = "Source",
  className,
  inline,
}: {
  sources: SourceRef[] | undefined;
  label?: string;
  className?: string;
  inline?: boolean;
}) {
  if (!sources || sources.length === 0) return null;

  if (inline) {
    return (
      <span className={cn("inline-flex flex-wrap items-center gap-1.5", className)}>
        <span className="text-small text-ink-subtle">{label}:</span>
        {sources.map((source) => (
          <a
            key={source.id}
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            title={`${source.title} — fetched ${source.fetched_at}`}
            className={cn(
              "inline-flex items-center gap-1 rounded text-small text-accent-700",
              "underline decoration-accent-300 decoration-dotted underline-offset-2",
              "transition-colors hover:decoration-solid dark:text-accent-300",
            )}
          >
            {source.id}
            <ExternalLink aria-hidden="true" className="size-3" />
          </a>
        ))}
      </span>
    );
  }

  return (
    <ul className={cn("space-y-1", className)}>
      {sources.map((source) => (
        <li key={source.id}>
          <a
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(
              "group inline-flex items-start gap-1.5 text-small text-ink-muted",
              "transition-colors hover:text-accent-700 dark:hover:text-accent-300",
            )}
          >
            <ExternalLink aria-hidden="true" className="mt-0.5 size-3 shrink-0" />
            <span>
              <span className="group-hover:underline">{source.title}</span>
              <span className="ml-1.5 text-ink-subtle">
                (read {source.fetched_at})
              </span>
            </span>
          </a>
        </li>
      ))}
    </ul>
  );
}

/**
 * Source citations given as bare knowledge-base ids.
 *
 * Fit-assessment requirements, advantages and gaps cite sources as ids (`["S4", "S8"]`)
 * while the assessment as a whole carries the resolved refs. This resolves the former
 * against the latter so a citation is a real link wherever it appears. An id with no
 * match is still shown — as a plain token rather than a broken link — because silently
 * dropping a citation is worse than showing one we cannot resolve.
 */
export function SourceIds({
  ids,
  catalogue,
  label = "Source",
  className,
  inline = true,
}: {
  ids: string[] | undefined;
  catalogue: SourceRef[];
  label?: string;
  className?: string;
  inline?: boolean;
}) {
  const resolved = React.useMemo(() => {
    const byId = new Map(catalogue.map((source) => [source.id, source]));
    const hits: SourceRef[] = [];
    const misses: string[] = [];
    for (const id of ids ?? []) {
      const match = byId.get(id);
      if (match) hits.push(match);
      else misses.push(id);
    }
    return { hits, misses };
  }, [ids, catalogue]);

  if (resolved.hits.length === 0 && resolved.misses.length === 0) return null;

  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1.5", className)}>
      <SourceList sources={resolved.hits} label={label} inline={inline} />
      {resolved.misses.map((id) => (
        <span
          key={id}
          title="Cited in the knowledge base; no link resolved for this id."
          className="text-small text-ink-subtle"
        >
          {id}
        </span>
      ))}
    </span>
  );
}

// =====================================================================================
// Playbook trust
// =====================================================================================

const APPROVAL_PRESENTATION: Record<
  PlaybookListItem["approval_status"],
  { tone: BadgeTone; label: string; icon: React.ReactNode }
> = {
  approved: { tone: "verified", label: "Verified", icon: <ShieldCheck /> },
  draft: { tone: "unverified", label: "Unreviewed draft", icon: <FileQuestion /> },
  in_review: { tone: "unverified", label: "Changes requested", icon: <FileQuestion /> },
  rejected: { tone: "critical", label: "Rejected", icon: <Ban /> },
  deprecated: { tone: "gated", label: "Deprecated", icon: <Archive /> },
};

/**
 * A playbook's trust state.
 *
 * Reads `approval_status` rather than `is_trusted` alone, because the four untrusted
 * states mean different things to a reviewer — and "deprecated" must not look like
 * "rejected".
 */
export function TrustBadge({
  status,
  isTrusted,
  size = "md",
  className,
}: {
  status: PlaybookListItem["approval_status"];
  isTrusted?: boolean;
  size?: "sm" | "md";
  className?: string;
}) {
  const presentation = APPROVAL_PRESENTATION[status];
  // Approved-but-not-shared is still not offerable, so it must not read as "Verified".
  const label =
    status === "approved" && isTrusted === false ? "Approved, not shared" : presentation.label;
  return (
    <Badge
      tone={status === "approved" && isTrusted === false ? "caution" : presentation.tone}
      size={size}
      icon={presentation.icon}
      className={className}
    >
      {label}
    </Badge>
  );
}

/**
 * The full trust notice.
 *
 * The backend writes one sentence stating exactly what a playbook's status means. It is
 * rendered verbatim so a client cannot reimplement — and subtly misstate — the policy.
 */
export function TrustNotice({
  playbook,
  className,
}: {
  playbook: Pick<
    PlaybookListItem,
    "approval_status" | "is_trusted" | "trust_notice" | "is_review_overdue"
  >;
  className?: string;
}) {
  const trusted = playbook.is_trusted;
  const tone = trusted
    ? playbook.is_review_overdue
      ? "caution"
      : "verified"
    : playbook.approval_status === "deprecated"
      ? "gated"
      : "unverified";

  const toneClasses: Record<string, string> = {
    verified: "border-verified/25 bg-verified-soft",
    caution: "border-caution/30 bg-caution-soft",
    unverified: "border-unverified/30 bg-unverified-soft",
    gated: "border-gated/25 bg-gated-soft",
  };

  return (
    <div
      className={cn(
        "flex items-start gap-2.5 rounded-md border px-3.5 py-3",
        toneClasses[tone],
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "mt-0.5 shrink-0 [&>svg]:size-4",
          trusted && !playbook.is_review_overdue ? "text-verified" : "text-caution",
        )}
      >
        {trusted ? <ShieldCheck /> : <TriangleAlert />}
      </span>
      <div className="min-w-0">
        <p className="text-small font-medium text-ink">
          {trusted ? "Verified knowledge" : "Not verified knowledge"}
        </p>
        <p className="mt-0.5 text-small text-ink-muted">{playbook.trust_notice}</p>
      </div>
    </div>
  );
}

// =====================================================================================
// Compatibility gate
// =====================================================================================

const GATE_PRESENTATION: Record<
  GateStatus,
  { tone: BadgeTone; label: string; icon: React.ReactNode }
> = {
  clean: { tone: "positive", label: "Applies to you", icon: <BadgeCheck /> },
  penalised: { tone: "caution", label: "Partly applicable", icon: <AlertTriangle /> },
  gated: { tone: "gated", label: "Does not apply", icon: <Ban /> },
};

export function GateBadge({
  status,
  size = "sm",
  className,
}: {
  status: GateStatus;
  size?: "sm" | "md";
  className?: string;
}) {
  const presentation = GATE_PRESENTATION[status];
  return (
    <Badge tone={presentation.tone} size={size} icon={presentation.icon} className={className}>
      {presentation.label}
    </Badge>
  );
}

/** The gate decision with its written reason, which is what makes it actionable. */
export function GateNotice({
  status,
  reason,
  className,
}: {
  status: GateStatus;
  reason: string;
  className?: string;
}) {
  if (status === "clean" || !reason) return null;
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 rounded-md border px-3 py-2.5",
        status === "gated"
          ? "border-gated/25 bg-gated-soft"
          : "border-caution/30 bg-caution-soft",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "mt-0.5 shrink-0 [&>svg]:size-4",
          status === "gated" ? "text-gated" : "text-caution",
        )}
      >
        {status === "gated" ? <Ban /> : <AlertTriangle />}
      </span>
      <p className="text-small text-ink-muted">{reason}</p>
    </div>
  );
}

// =====================================================================================
// Synthetic data
// =====================================================================================

export function SimulatedBadge({
  label = "Synthetic",
  size = "sm",
  className,
}: {
  label?: string;
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <Badge tone="simulated" size={size} icon={<FlaskConical />} className={className}>
      {label}
    </Badge>
  );
}

/**
 * A prominent notice that the data on screen is synthetic.
 *
 * Used wherever seeded tickets, clusters or playbooks appear. The brief requires this, and
 * it is also the right thing: a prospect who later discovers the incident history was
 * invented loses trust in everything else they were shown.
 */
export function SimulatedNotice({
  children,
  className,
  compact,
}: {
  children: React.ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 rounded-md border border-simulated/25 bg-simulated-soft",
        compact ? "px-3 py-2" : "px-3.5 py-3",
        className,
      )}
    >
      <span aria-hidden="true" className="mt-0.5 shrink-0 text-simulated [&>svg]:size-4">
        <FlaskConical />
      </span>
      <p className={cn("text-small text-ink-muted", compact && "text-[13px]")}>{children}</p>
    </div>
  );
}

/** A labelled notice that an integration is simulated rather than connected. */
export function IntegrationModeBadge({
  mode,
  className,
}: {
  mode: "demo" | "configured" | "connected";
  className?: string;
}) {
  const presentation: Record<typeof mode, { tone: BadgeTone; label: string }> = {
    demo: { tone: "simulated", label: "Simulated" },
    configured: { tone: "caution", label: "Configured, unverified" },
    connected: { tone: "positive", label: "Connected" },
  };
  const { tone, label } = presentation[mode];
  return (
    <Badge
      tone={tone}
      size="sm"
      icon={mode === "connected" ? <BadgeCheck /> : <FlaskConical />}
      className={className}
    >
      {label}
    </Badge>
  );
}

// =====================================================================================
// Metric confidence
// =====================================================================================

/**
 * How a metric was produced.
 *
 * `estimated` and `insufficient_data` are the important ones. An estimate presented as a
 * measurement is a lie with a decimal point; a null rendered as "0" is worse, because
 * "no data yet" and "it never happens" are opposite claims.
 */
export function ConfidenceBadge({
  confidence,
  className,
}: {
  confidence: MetricConfidence;
  className?: string;
}) {
  const presentation: Record<MetricConfidence, { tone: BadgeTone; label: string }> = {
    measured: { tone: "positive", label: "Measured" },
    estimated: { tone: "caution", label: "Estimated" },
    insufficient_data: { tone: "neutral", label: "Not enough data" },
    untested: { tone: "neutral", label: "Untested" },
  };
  const { tone, label } = presentation[confidence];
  return (
    <Badge tone={tone} size="sm" className={className}>
      {label}
    </Badge>
  );
}

// =====================================================================================
// Match evidence
// =====================================================================================

const EVIDENCE_PRESENTATION: Record<
  MatchEvidence["strength"],
  { dot: string; label: string }
> = {
  strong: { dot: "bg-positive", label: "Strong" },
  moderate: { dot: "bg-info", label: "Moderate" },
  weak: { dot: "bg-ink-subtle", label: "Weak" },
  negative: { dot: "bg-caution", label: "Against" },
};

/**
 * Why a match was proposed, including the reasons against it.
 *
 * Negative evidence is rendered, never filtered out. "Different component" and "resolution
 * never verified" are the entries that let an engineer dismiss a bad match in two seconds
 * — hiding them would make the list look more confident and be less useful.
 */
export function EvidenceList({
  evidence,
  className,
  max,
}: {
  evidence: MatchEvidence[];
  className?: string;
  max?: number;
}) {
  const [expanded, setExpanded] = React.useState(false);
  if (evidence.length === 0) return null;

  const limit = max ?? evidence.length;
  const shown = expanded ? evidence : evidence.slice(0, limit);
  const hidden = evidence.length - shown.length;

  return (
    <div className={cn("space-y-2", className)}>
      <ul className="space-y-2">
        {shown.map((item, index) => {
          const presentation = EVIDENCE_PRESENTATION[item.strength];
          return (
            <li key={`${item.kind}-${index}`} className="flex items-start gap-2.5">
              <span
                aria-hidden="true"
                className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", presentation.dot)}
              />
              <span className="min-w-0 text-small">
                <span
                  className={cn(
                    "font-medium",
                    item.strength === "negative" ? "text-caution" : "text-ink",
                  )}
                >
                  {item.label}
                </span>
                <span className="sr-only"> ({presentation.label} evidence)</span>
                <span className="text-ink-muted"> — {item.detail}</span>
              </span>
            </li>
          );
        })}
      </ul>
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="text-small font-medium text-accent-700 hover:underline dark:text-accent-300"
        >
          Show {hidden} more {hidden === 1 ? "reason" : "reasons"}
        </button>
      )}
    </div>
  );
}

// =====================================================================================
// Architecture graph claim status
// =====================================================================================

export const NODE_CLAIM_PRESENTATION: Record<
  NodeClaimStatus,
  { tone: BadgeTone; label: string; border: string; background: string; dashed: boolean }
> = {
  documented: {
    tone: "verified",
    label: "Documented",
    border: "border-accent-400",
    background: "bg-accent-50",
    dashed: false,
  },
  documented_integration: {
    tone: "positive",
    label: "Documented integration",
    border: "border-positive/50",
    background: "bg-positive-soft",
    dashed: false,
  },
  customer_system: {
    tone: "neutral",
    label: "Your system",
    border: "border-border-strong",
    background: "bg-surface-sunken",
    dashed: false,
  },
  conceptual: {
    tone: "info",
    label: "Conceptual",
    border: "border-info/50",
    background: "bg-info-soft",
    dashed: true,
  },
  needs_confirmation: {
    tone: "caution",
    label: "Needs confirmation",
    border: "border-caution/60",
    background: "bg-caution-soft",
    dashed: true,
  },
};

export function NodeClaimBadge({
  status,
  className,
}: {
  status: NodeClaimStatus;
  className?: string;
}) {
  const presentation = NODE_CLAIM_PRESENTATION[status];
  return (
    <Badge tone={presentation.tone} size="sm" className={className}>
      {presentation.label}
    </Badge>
  );
}

/** The architecture graph legend, from what the API returns. */
export function GraphLegend({
  legend,
  className,
}: {
  legend: { claim_status: NodeClaimStatus; label: string; meaning: string }[];
  className?: string;
}) {
  return (
    <div className={cn("space-y-2.5", className)}>
      <Eyebrow as="h3">Legend</Eyebrow>
      <dl className="space-y-2">
        {legend.map((entry) => {
          const presentation = NODE_CLAIM_PRESENTATION[entry.claim_status];
          return (
            <div key={entry.claim_status} className="flex items-start gap-2.5">
              <dt className="mt-0.5 shrink-0">
                <span
                  aria-hidden="true"
                  className={cn(
                    "block h-4 w-7 rounded-sm border-2",
                    presentation.border,
                    presentation.background,
                    presentation.dashed && "border-dashed",
                  )}
                />
              </dt>
              <dd className="min-w-0 text-small">
                <span className="font-medium text-ink">{entry.label}</span>
                <span className="text-ink-muted"> — {entry.meaning}</span>
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

// =====================================================================================
// Disclaimers
// =====================================================================================

/**
 * A disclaimer that has to be read rather than skimmed past.
 *
 * Used for the fit-assessment and architecture caveats. Bordered and tinted, not grey
 * 10px text in a footer — if it is worth saying it is worth seeing.
 */
export function Disclaimer({
  title,
  children,
  className,
  tone = "info",
}: {
  title?: string;
  children: React.ReactNode;
  className?: string;
  tone?: "info" | "caution";
}) {
  return (
    <aside
      className={cn(
        "rounded-lg border px-4 py-3.5",
        tone === "caution"
          ? "border-caution/30 bg-caution-soft"
          : "border-info/25 bg-info-soft",
        className,
      )}
    >
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden="true"
          className={cn(
            "mt-0.5 shrink-0 [&>svg]:size-4",
            tone === "caution" ? "text-caution" : "text-info",
          )}
        >
          <Info />
        </span>
        <div className="min-w-0 text-small text-ink-muted">
          {title && <p className="mb-1 font-medium text-ink">{title}</p>}
          {children}
        </div>
      </div>
    </aside>
  );
}

/**
 * Generated-content attribution.
 *
 * Shown wherever COMPASS displays composed or generated text, stating which provider
 * produced it. In demo mode that means saying plainly that no language model was involved.
 */
export function ProviderNotice({
  provider,
  isLive,
  notice,
  className,
}: {
  provider: string;
  isLive: boolean;
  notice?: string;
  className?: string;
}) {
  return (
    <p
      className={cn(
        "flex items-start gap-1.5 text-small text-ink-subtle",
        className,
      )}
    >
      <Info aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
      <span>
        {isLive ? (
          <>
            Generated by <span className="font-medium text-ink-muted">{provider}</span>,
            grounded in the sources listed above.
          </>
        ) : (
          (notice ??
            "Composed deterministically from the retrieved records listed above. No " +
              "language model was used.")
        )}
      </span>
    </p>
  );
}
