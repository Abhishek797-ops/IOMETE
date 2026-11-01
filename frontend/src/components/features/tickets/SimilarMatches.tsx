"use client";

import * as React from "react";

import { ArrowRight, Ban, PlayCircle, RefreshCw, ShieldCheck } from "lucide-react";

import { api } from "@/lib/api";
import { useMutation } from "@/lib/hooks";
import type {
  Execution,
  PlaybookMatch,
  SimilarSearchResult,
  SimilarityMatch,
} from "@/lib/types";
import { cn, percent } from "@/lib/utils";

import {
  Badge,
  Button,
  Card,
  ChannelBars,
  Disclosure,
  Divider,
  EvidenceList,
  Eyebrow,
  FormError,
  GateBadge,
  ScoreTrio,
  TrustBadge,
} from "@/components/ui";

/**
 * What COMPASS found for this ticket.
 *
 * The central claim of the product is made here, so the central failure mode is guarded
 * here too: **similarity is not root cause**. A paraphrase of another ticket can score
 * 1.0 similarity while the underlying problem is unrelated, so the three scores are shown
 * side by side with their own explanations and never collapsed into one number.
 *
 * Version and environment gating is applied before relevance, not after. A resolution
 * from a product version that cannot apply to this customer is shown as blocked with the
 * reason — not quietly ranked lower, and never offered as runnable.
 */
export function SimilarMatches({
  ticketId,
  initial,
  canRunReplay,
  onReplayStarted,
}: {
  ticketId: string;
  initial: SimilarSearchResult;
  canRunReplay: boolean;
  onReplayStarted?: (execution: Execution) => void;
}) {
  const [result, setResult] = React.useState(initial);

  const refresh = useMutation(
    async () => api.similarTickets(ticketId, { refresh: true }),
    { onSuccess: setResult },
  );

  const offerable = result.playbook_matches.filter(
    (match) => match.gate_status === "clean",
  );
  const blocked = result.playbook_matches.filter((match) => match.gate_status !== "clean");

  return (
    <div className="space-y-6">
      {/* --------------------------------------------------------- Playbooks */}
      <section>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <Eyebrow as="h2">Verified resolutions</Eyebrow>
            <h3 className="mt-1.5 text-h2 text-ink">
              {offerable.length > 0
                ? "Somebody has already solved this"
                : "No verified resolution matches yet"}
            </h3>
            <p className="mt-1.5 text-small text-ink-muted measure">
              {offerable.length > 0
                ? "A playbook an IOMETE engineer wrote from a real investigation, reviewed and approved before it was offered to anyone. You run it; COMPASS does not."
                : "Nothing in the approved knowledge base applies to your environment. That is COMPASS declining to guess rather than a dead end — an engineer picks this up from here."}
            </p>
          </div>
          <Button
            variant="ghost"
            onClick={() => void refresh.run()}
            loading={refresh.pending}
            icon={<RefreshCw />}
          >
            Search again
          </Button>
        </div>

        <FormError error={refresh.error} className="mt-4" />

        {offerable.length > 0 && (
          <ul className="mt-5 space-y-4">
            {offerable.map((match) => (
              <li key={match.id}>
                <PlaybookMatchCard
                  ticketId={ticketId}
                  match={match}
                  canRunReplay={canRunReplay}
                  {...(onReplayStarted ? { onReplayStarted } : {})}
                />
              </li>
            ))}
          </ul>
        )}

        {blocked.length > 0 && (
          <div className="mt-5">
            <Disclosure
              summary={
                <span className="text-small text-ink-muted">
                  {blocked.length} resolution{blocked.length === 1 ? "" : "s"} ruled out
                  for your environment
                </span>
              }
            >
              <p className="mb-3.5 text-small text-ink-muted measure">
                These match the symptoms but cannot be applied here. They are shown so the
                reasoning is visible, and they are deliberately not runnable.
              </p>
              <ul className="space-y-3">
                {blocked.map((match) => (
                  <li key={match.id}>
                    <BlockedMatch match={match} />
                  </li>
                ))}
              </ul>
            </Disclosure>
          </div>
        )}
      </section>

      <Divider />

      {/* ----------------------------------------------------- Similar tickets */}
      <section>
        <Eyebrow as="h2">Similar investigations</Eyebrow>
        <h3 className="mt-1.5 text-h2 text-ink">
          {result.matches.length > 0
            ? "Prior tickets that look like yours"
            : "No prior ticket resembles this one"}
        </h3>
        <p className="mt-1.5 text-small text-ink-muted measure">
          Ranked by four independent signals, not one. Read the three scores separately —
          a report can be worded almost identically to another and still have a completely
          different cause.
        </p>

        {result.note && (
          <p className="mt-3 text-[11px] text-ink-subtle">{result.note}</p>
        )}

        <ul className="mt-5 space-y-4">
          {result.matches.map((match) => (
            <li key={match.id}>
              <SimilarTicketCard match={match} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function PlaybookMatchCard({
  ticketId,
  match,
  canRunReplay,
  onReplayStarted,
}: {
  ticketId: string;
  match: PlaybookMatch;
  canRunReplay: boolean;
  onReplayStarted?: (execution: Execution) => void;
}) {
  const start = useMutation(
    async () => api.startExecution(ticketId, match.playbook.id),
    { onSuccess: (execution) => onReplayStarted?.(execution) },
  );

  return (
    <Card className="border-accent-200">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-h3 text-ink">{match.playbook.title}</h4>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <TrustBadge
              status={match.playbook.approval_status}
              isTrusted={match.playbook.is_trusted}
              size="sm"
            />
            <GateBadge status={match.gate_status} size="sm" />
            <Badge tone="neutral" size="sm">
              v{match.playbook.version}
            </Badge>
            {match.playbook.step_count !== undefined && (
              <Badge tone="neutral" size="sm">
                {match.playbook.step_count} steps
              </Badge>
            )}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[11px] uppercase tracking-wide text-ink-subtle">
            Resolution confidence
          </p>
          <p className="text-h2 tabular text-ink">
            {percent(match.resolution_confidence)}
          </p>
        </div>
      </div>

      {match.playbook.description && (
        <p className="mt-3.5 text-small text-ink-muted measure">
          {match.playbook.description}
        </p>
      )}

      <div className="mt-4 rounded-md bg-surface-sunken px-3.5 py-3">
        <p className="text-small text-ink-muted">
          <span className="font-medium text-ink">Why it applies: </span>
          {match.gate_reason}
        </p>
      </div>

      {match.evidence.length > 0 && (
        <div className="mt-4">
          <EvidenceList evidence={match.evidence} />
        </div>
      )}

      <Divider className="my-5" />

      <div className="flex flex-wrap items-center gap-3">
        {canRunReplay ? (
          <Button
            variant="primary"
            onClick={() => void start.run()}
            loading={start.pending}
            icon={<PlayCircle />}
          >
            Start the replay
          </Button>
        ) : (
          <p className="text-small text-ink-muted">
            An engineer on your account can run this resolution.
          </p>
        )}
        <span className="inline-flex items-center gap-1.5 text-small text-ink-subtle">
          <ShieldCheck aria-hidden="true" className="size-3.5" />
          Guided, step by step. COMPASS executes nothing.
        </span>
      </div>

      <FormError error={start.error} className="mt-3" />
    </Card>
  );
}

function BlockedMatch({ match }: { match: PlaybookMatch }) {
  return (
    <Card tone="flat" className="border-gated/30">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-small font-medium text-ink">{match.playbook.title}</h4>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <GateBadge status={match.gate_status} size="sm" />
            <Badge tone="neutral" size="sm">
              v{match.playbook.version}
            </Badge>
          </div>
        </div>
        <Ban aria-hidden="true" className="size-4 shrink-0 text-ink-subtle" />
      </div>
      <p className="mt-3 text-small text-ink-muted">{match.gate_reason}</p>
    </Card>
  );
}

function SimilarTicketCard({ match }: { match: SimilarityMatch }) {
  const weak = match.diagnosis_confidence < 0.25;

  return (
    <Card tone={weak ? "flat" : "raised"}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-small text-ink-subtle">
              {match.matched_ticket.reference}
            </span>
            <GateBadge status={match.gate_status} size="sm" />
          </p>
          <h4 className="mt-1.5 text-h3 text-ink">{match.matched_ticket.title}</h4>
        </div>
        <span
          aria-hidden="true"
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold tabular",
            "bg-surface-inset text-ink-muted",
          )}
        >
          #{match.rank}
        </span>
      </div>

      <div className="mt-5">
        <ScoreTrio
          similarity={match.similarity_score}
          diagnosis={match.diagnosis_confidence}
          resolution={match.resolution_confidence}
          explanations={match.score_explanations}
        />
      </div>

      {weak && (
        <p className="mt-4 rounded-md border border-caution/30 bg-caution-soft px-3.5 py-2.5 text-small text-ink-muted">
          <span className="font-medium text-ink">Read this one carefully. </span>
          The wording is alike but COMPASS found little evidence of a shared cause. A high
          similarity score with a low diagnosis score usually means two different problems
          described in the same words.
        </p>
      )}

      {match.matched_symptom_labels.length > 0 && (
        <ul className="mt-4 flex flex-wrap gap-1.5">
          {match.matched_symptom_labels.map((symptom) => (
            <li key={symptom}>
              <Badge tone="neutral" size="sm">
                {symptom}
              </Badge>
            </li>
          ))}
        </ul>
      )}

      {match.evidence.length > 0 && (
        <div className="mt-4">
          <EvidenceList evidence={match.evidence} />
        </div>
      )}

      <Divider className="my-5" />

      <Disclosure
        summary={
          <span className="text-small text-ink-muted">
            How this was ranked
            <span className="ml-2 text-ink-subtle">
              ({match.retrieval_backend} backend)
            </span>
          </span>
        }
      >
        <p className="mb-3.5 text-small text-ink-muted measure">
          Four independent channels, fused with weighted reciprocal rank. An exact error
          code match counts for more than prose similarity, which is why a reworded ticket
          with the same error outranks a semantically similar one without it.
        </p>
        <ChannelBars scores={match.channel_scores} />
      </Disclosure>

      <p className="mt-4">
        <a
          href={`/app/history/${match.matched_ticket.id}`}
          className="inline-flex items-center gap-1 text-small font-medium text-accent-700 underline decoration-accent-300 underline-offset-2 dark:text-accent-400"
        >
          Read that investigation
          <ArrowRight aria-hidden="true" className="size-3.5" />
        </a>
      </p>
    </Card>
  );
}
