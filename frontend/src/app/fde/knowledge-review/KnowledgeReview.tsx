"use client";

import * as React from "react";

import { useRouter } from "next/navigation";

import {
  CheckCircle2,
  FileQuestion,
  Sparkles,
  ThumbsDown,
  TimerReset,
  Wand2,
} from "lucide-react";

import { api } from "@/lib/api";
import { canApproveKnowledge, useAuth } from "@/lib/auth";
import { useMutation, useResource } from "@/lib/hooks";
import type { ExtractionResult, PlaybookListItem, TicketListItem } from "@/lib/types";
import { cn, relativeTime } from "@/lib/utils";

import {
  Badge,
  Button,
  Card,
  Dialog,
  Divider,
  EmptyState,
  ErrorState,
  Eyebrow,
  FormError,
  LoadingState,
  PageHeader,
  Tabs,
  Textarea,
  TrustNotice,
  useToast,
} from "@/components/ui";

/**
 * Knowledge compounding, where it actually happens.
 *
 * Every resolved investigation is a candidate for reuse, but nothing becomes reusable
 * knowledge until a qualified human says so. This queue is that gate, and it is the
 * reason COMPASS can claim a playbook is verified at all:
 *
 *  - a draft is **never** presented as trusted, and carries its status everywhere
 *  - approving is an explicit act by somebody with the role, recorded against them
 *  - a verified resolution with no write-up is shown as a gap, because an investigation
 *    nobody wrote down is one the next engineer has to repeat
 */
export function KnowledgeReview() {
  const router = useRouter();
  const { user } = useAuth();

  const queue = useResource(async () => api.knowledgeReviewQueue(), []);
  const canApprove = canApproveKnowledge(user);

  const [decision, setDecision] = React.useState<{
    playbook: PlaybookListItem;
    action: "approve" | "reject" | "changes";
  } | null>(null);

  if (queue.loading && !queue.data) return <LoadingState label="Loading the review queue" />;
  if (queue.error && !queue.data) {
    return <ErrorState error={queue.error} onRetry={queue.reload} />;
  }
  if (!queue.data) return null;

  const data = queue.data;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Knowledge"
        title="Review queue"
        description="Nothing becomes verified knowledge without a human approving it. This is that step."
      />

      {!canApprove && (
        <Card tone="sunken" className="border-caution/30">
          <p className="text-small text-ink-muted">
            You can read this queue but not approve from it. Approving knowledge requires
            an FDE lead or platform administrator — the server enforces that regardless of
            what this page shows.
          </p>
        </Card>
      )}

      <Tabs
        persistKey="fde.knowledge-review"
        items={[
          { id: "drafts", label: "Awaiting approval", count: data.counts.drafts },
          {
            id: "changes",
            label: "Changes requested",
            count: data.counts.changes_requested,
          },
          {
            id: "gaps",
            label: "Unwritten resolutions",
            count: data.counts.verified_tickets_without_a_playbook,
          },
          { id: "overdue", label: "Review overdue", count: data.counts.review_overdue },
        ]}
      >
        {(tab) => (
          <>
            {tab === "drafts" && (
              <DraftList
                drafts={data.drafts}
                canApprove={canApprove}
                onDecide={(playbook, action) => setDecision({ playbook, action })}
                emptyTitle="Nothing waiting"
                emptyBody="Every extracted draft has been reviewed. New ones appear here as investigations are written up."
              />
            )}

            {tab === "changes" && (
              <DraftList
                drafts={data.changes_requested}
                canApprove={canApprove}
                onDecide={(playbook, action) => setDecision({ playbook, action })}
                emptyTitle="No rework outstanding"
                emptyBody="Nothing has been sent back to its author."
              />
            )}

            {tab === "gaps" && (
              <UnwrittenResolutions
                tickets={data.verified_tickets_without_a_playbook}
                note={data.notes.verified_tickets_without_a_playbook ?? ""}
                onExtracted={() => void queue.reload()}
              />
            )}

            {tab === "overdue" && (
              <DraftList
                drafts={data.review_overdue}
                canApprove={canApprove}
                onDecide={(playbook, action) => setDecision({ playbook, action })}
                emptyTitle="Nothing is stale"
                emptyBody="Every approved playbook is within its review window."
              />
            )}
          </>
        )}
      </Tabs>

      {decision && (
        <DecisionDialog
          playbook={decision.playbook}
          action={decision.action}
          onClose={() => setDecision(null)}
          onDone={() => {
            setDecision(null);
            void queue.reload();
            router.refresh();
          }}
        />
      )}
    </div>
  );
}

function DraftList({
  drafts,
  canApprove,
  onDecide,
  emptyTitle,
  emptyBody,
}: {
  drafts: PlaybookListItem[];
  canApprove: boolean;
  onDecide: (playbook: PlaybookListItem, action: "approve" | "reject" | "changes") => void;
  emptyTitle: string;
  emptyBody: string;
}) {
  if (drafts.length === 0) {
    return (
      <EmptyState icon={<CheckCircle2 />} title={emptyTitle} description={emptyBody} />
    );
  }

  return (
    <ul className="space-y-4">
      {drafts.map((playbook) => (
        <li key={playbook.id}>
          <Card>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-h3 text-ink">{playbook.title}</h3>
                <p className="mt-1.5 text-small text-ink-subtle">
                  {playbook.component_label} · {playbook.category_label} ·{" "}
                  {playbook.step_count} steps · created{" "}
                  {relativeTime(playbook.created_at)}
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                <Badge tone="unverified" size="sm">
                  {playbook.approval_status_label}
                </Badge>
                <Badge tone="neutral" size="sm">
                  v{playbook.version}
                </Badge>
              </div>
            </div>

            <p className="mt-3.5 text-small text-ink-muted measure">
              {playbook.description}
            </p>

            <div className="mt-4">
              <TrustNotice playbook={playbook} />
            </div>

            <dl className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-3">
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-ink-subtle">
                  Applies to
                </dt>
                <dd className="mt-0.5 text-small text-ink">
                  {playbook.applicable_versions || "any version"}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-ink-subtle">
                  Risk
                </dt>
                <dd className="mt-0.5 text-small text-ink">{playbook.risk_level_label}</dd>
              </div>
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-ink-subtle">
                  Written by
                </dt>
                <dd className="mt-0.5 text-small text-ink">{playbook.generated_by}</dd>
              </div>
            </dl>

            {playbook.symptom_labels.length > 0 && (
              <ul className="mt-4 flex flex-wrap gap-1.5">
                {playbook.symptom_labels.map((symptom) => (
                  <li key={symptom}>
                    <Badge tone="neutral" size="sm">
                      {symptom}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}

            <Divider className="my-5" />

            <div className="flex flex-wrap items-center gap-2.5">
              <a
                href={`/fde/playbooks/${playbook.id}`}
                className="text-small font-medium text-accent-700 underline decoration-accent-300 underline-offset-2 dark:text-accent-400"
              >
                Read every step
              </a>
              <span className="ml-auto flex flex-wrap gap-2.5">
                {/* Secondary, not ghost: a reviewer must be able to see at a glance that
                    rejecting is as available as approving. A ghost button beside a filled
                    one reads as disabled, which quietly biases the queue towards approval. */}
                <Button
                  variant="secondary"
                  disabled={!canApprove}
                  onClick={() => onDecide(playbook, "changes")}
                  icon={<TimerReset />}
                >
                  Request changes
                </Button>
                <Button
                  variant="secondary"
                  disabled={!canApprove}
                  onClick={() => onDecide(playbook, "reject")}
                  icon={<ThumbsDown />}
                >
                  Reject
                </Button>
                <Button
                  variant="primary"
                  disabled={!canApprove}
                  onClick={() => onDecide(playbook, "approve")}
                  icon={<CheckCircle2 />}
                >
                  Approve
                </Button>
              </span>
            </div>
          </Card>
        </li>
      ))}
    </ul>
  );
}

/**
 * Verified resolutions nobody wrote up.
 *
 * The compounding loop's leak. Each row is an investigation that worked and was lost;
 * extracting it produces a *draft*, never an approved playbook, which is why the button
 * says what it does.
 */
function UnwrittenResolutions({
  tickets,
  note,
  onExtracted,
}: {
  tickets: TicketListItem[];
  note: string;
  onExtracted: () => void;
}) {
  if (tickets.length === 0) {
    return (
      <EmptyState
        icon={<Sparkles />}
        title="Everything is written up"
        description="Every verified resolution has a playbook. This is the state the loop is supposed to reach."
      />
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-small text-ink-muted measure">{note}</p>
      <ul className="space-y-3">
        {tickets.map((ticket) => (
          <li key={ticket.id}>
            <ExtractRow ticket={ticket} onExtracted={onExtracted} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * One unwritten resolution, and the outcome of trying to extract it.
 *
 * Extraction has three honest outcomes and the row reports whichever happened. It
 * deliberately does not claim a draft was created when the extractor declined: the most
 * common result on a mature knowledge base is "an existing playbook already covers this",
 * and reporting that as success would corrupt the very signal this queue exists to give.
 */
function ExtractRow({
  ticket,
  onExtracted,
}: {
  ticket: TicketListItem;
  onExtracted: () => void;
}) {
  const [result, setResult] = React.useState<ExtractionResult | null>(null);
  const toast = useToast();

  const extract = useMutation(async () => api.extractKnowledge(ticket.id), {
    onSuccess: (outcome) => {
      setResult(outcome);
      if (outcome.playbook) {
        toast.success(
          "Draft extracted",
          "It is in the approval queue — unverified until somebody reviews it.",
        );
      } else if (outcome.duplicate_of) {
        toast.info(
          "No draft created",
          "An existing playbook already covers this error signature.",
        );
      } else {
        toast.info("No draft created", "The extractor found nothing reusable here.");
      }
      onExtracted();
    },
  });

  return (
    <Card tone="flat">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-small text-ink-subtle">{ticket.reference}</p>
          <h3 className="mt-1 text-small font-medium text-ink">{ticket.title}</h3>
          <p className="mt-1.5 text-[11px] text-ink-subtle">
            {ticket.organization_name} · {ticket.component_label} · resolved{" "}
            {ticket.resolved_at ? relativeTime(ticket.resolved_at) : "—"}
          </p>
        </div>
        <Button
          variant="secondary"
          onClick={() => void extract.run()}
          loading={extract.pending}
          icon={<Wand2 />}
        >
          {result ? "Extract again" : "Extract a draft"}
        </Button>
      </div>

      <FormError error={extract.error} className="mt-3" />

      {result && (
        <div
          className={cn(
            "mt-3.5 rounded-md border px-3.5 py-3",
            result.playbook
              ? "border-positive/30 bg-positive-soft"
              : "border-info/25 bg-info-soft",
          )}
        >
          <p className="text-small font-medium text-ink">
            {result.playbook
              ? "Draft created — it is now awaiting approval"
              : result.duplicate_of
                ? "No draft created: already covered"
                : "No draft created"}
          </p>

          {result.duplicate_of && (
            <p className="mt-1 text-small text-ink-muted">
              <span className="font-medium text-ink">
                {result.duplicate_of.title}
              </span>{" "}
              (v{result.duplicate_of.version}) already covers this error signature. Link
              the ticket to it rather than adding a near-duplicate to the knowledge base.
            </p>
          )}

          {result.notes.length > 0 && (
            <ul className="mt-2 space-y-1">
              {result.notes.map((note) => (
                <li key={note} className="text-small text-ink-muted">
                  — {note}
                </li>
              ))}
            </ul>
          )}

          {result.redaction_flags.length > 0 && (
            <p className="mt-2 text-small text-caution">
              Redaction flags: {result.redaction_flags.join(", ")}
            </p>
          )}

          {!result.ai.is_live_model && result.ai.notice && (
            <p className="mt-2 text-[11px] text-ink-subtle">{result.ai.notice}</p>
          )}
        </div>
      )}
    </Card>
  );
}

/**
 * The approval decision.
 *
 * A reason is mandatory for every outcome, approval included. An approval with no stated
 * basis is indistinguishable from a rubber stamp, and this record is what a customer is
 * trusting when COMPASS tells them a resolution is verified.
 */
function DecisionDialog({
  playbook,
  action,
  onClose,
  onDone,
}: {
  playbook: PlaybookListItem;
  action: "approve" | "reject" | "changes";
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = React.useState("");
  const [touched, setTouched] = React.useState(false);
  const toast = useToast();

  const copy = {
    approve: {
      title: "Approve this playbook",
      body: "Approving makes it offerable to customers whose environment matches. State what you checked — this record is what the word 'verified' rests on.",
      label: "What did you verify?",
      cta: "Approve and publish",
    },
    reject: {
      title: "Reject this draft",
      body: "It will not be offered to anyone. The reason is kept with the draft so the next person does not repeat the work.",
      label: "Why is this wrong?",
      cta: "Reject",
    },
    changes: {
      title: "Send this back",
      body: "The draft returns to its author with your note.",
      label: "What needs changing?",
      cta: "Request changes",
    },
  }[action];

  const submit = useMutation(
    async () => {
      if (action === "approve") {
        return api.approvePlaybook(playbook.id, { note: reason });
      }
      if (action === "reject") return api.rejectPlaybook(playbook.id, reason);
      return api.requestPlaybookChanges(playbook.id, reason);
    },
    {
      onSuccess: () => {
        toast.success(
          action === "approve" ? "Approved" : "Recorded",
          action === "approve"
            ? "It is now offerable to matching environments."
            : "The author has your note.",
        );
        onDone();
      },
    },
  );

  return (
    <Dialog
      open
      onClose={onClose}
      title={copy.title}
      tone={action === "approve" ? "default" : "caution"}
    >
      <p className="text-small text-ink-muted">{copy.body}</p>

      <div className="mt-4 rounded-md bg-surface-sunken px-3.5 py-3">
        <Eyebrow as="h3">Playbook</Eyebrow>
        <p className="mt-1 text-small font-medium text-ink">{playbook.title}</p>
        <p className="mt-0.5 text-[11px] text-ink-subtle">
          v{playbook.version} · {playbook.step_count} steps · {playbook.risk_level_label}
        </p>
      </div>

      <div className="mt-4">
        <Textarea
          label={copy.label}
          required
          rows={4}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          error={touched && !reason.trim() ? "A reason is required." : null}
        />
      </div>

      <FormError error={submit.error} className="mt-3" />

      <div className="mt-5 flex flex-wrap justify-end gap-2.5">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant={action === "approve" ? "primary" : "danger"}
          loading={submit.pending}
          onClick={() => {
            setTouched(true);
            if (!reason.trim()) return;
            void submit.run();
          }}
          icon={action === "approve" ? <CheckCircle2 /> : <FileQuestion />}
        >
          {copy.cta}
        </Button>
      </div>
    </Dialog>
  );
}
