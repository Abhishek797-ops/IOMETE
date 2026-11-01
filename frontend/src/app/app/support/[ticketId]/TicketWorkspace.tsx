"use client";

import * as React from "react";

import Link from "next/link";

import { ArrowLeft, FileWarning, Inbox, ShieldCheck } from "lucide-react";

import { api } from "@/lib/api";
import { hasMembershipRole, useAuth } from "@/lib/auth";
import { useResource } from "@/lib/hooks";
import type { Execution, Ticket } from "@/lib/types";
import { formatDateTime, relativeTime, severityTone, statusTone } from "@/lib/utils";

import { ReplayIntro, ReplayRunner } from "@/components/features/replay/ReplayRunner";
import { SimilarMatches } from "@/components/features/tickets/SimilarMatches";
import {
  Badge,
  Card,
  DetailList,
  DetailRow,
  Divider,
  ErrorState,
  Eyebrow,
  KeyValueGrid,
  LoadingState,
  PageHeader,
  SimulatedBadge,
  Tabs,
} from "@/components/ui";

/**
 * A customer's view of one ticket.
 *
 * The order is the product thesis: the problem, then what COMPASS already knows about
 * it, then — if an applicable verified resolution exists — the replay. A customer who
 * can resolve their own incident from prior work never has to open a conversation with
 * an engineer, and that is the entire point.
 */
export function TicketWorkspace({ ticketId }: { ticketId: string }) {
  const { user } = useAuth();
  /** Set when this session started a replay. Otherwise one is resumed from the server. */
  const [started, setStarted] = React.useState<Execution | null>(null);

  const ticket = useResource<Ticket>(async () => api.ticket(ticketId), [ticketId]);
  const similar = useResource(async () => api.similarTickets(ticketId), [ticketId]);
  const executions = useResource(
    async () => api.executions({ ticket: ticketId }),
    [ticketId],
  );

  if (ticket.loading && !ticket.data) {
    return <LoadingState label="Opening the ticket" />;
  }
  if (ticket.error && !ticket.data) {
    return <ErrorState error={ticket.error} onRetry={ticket.reload} />;
  }
  if (!ticket.data) return null;

  const data = ticket.data;

  // Derived, not stored: an unfinished replay resumes where it was left. Keeping this out
  // of state means there is no window where the page shows a stale execution.
  const execution =
    started ??
    executions.data?.results.find((item) => item.status === "in_progress") ??
    null;
  // Who may drive a replay. The server decides for real; this only chooses whether to
  // offer the button, so a viewer is not invited into something they will be refused.
  const canRunReplay = hasMembershipRole(user, "engineer");

  return (
    <div className="space-y-7">
      <div>
        <Link
          href="/app/support"
          className="inline-flex items-center gap-1.5 text-small text-ink-muted transition-colors hover:text-ink"
        >
          <ArrowLeft aria-hidden="true" className="size-3.5" />
          All tickets
        </Link>
      </div>

      <PageHeader
        eyebrow={data.reference}
        title={data.title}
        description={`Raised ${relativeTime(data.created_at)} · ${data.component_label}`}
      >
        <div className="flex flex-wrap gap-2">
          <Badge tone={statusTone(data.status)}>{data.status_label}</Badge>
          <Badge tone={severityTone(data.severity)}>{data.severity_label}</Badge>
          {data.is_synthetic && <SimulatedBadge />}
        </div>
      </PageHeader>

      {/* --------------------------------------------------------- The problem */}
      <Card>
        <Eyebrow as="h2">What you reported</Eyebrow>
        <p className="mt-3 whitespace-pre-wrap text-body leading-relaxed text-ink-muted measure">
          {data.description}
        </p>

        {data.error_message && (
          <div className="mt-4 rounded-md border border-critical/25 bg-critical-soft px-3.5 py-3">
            <p className="text-[11px] uppercase tracking-wide text-ink-subtle">
              Error reported
            </p>
            <p className="mt-1 font-mono text-[0.8125rem] text-ink">{data.error_message}</p>
          </div>
        )}

        {data.redaction_notice && (
          <p className="mt-4 flex items-start gap-2 text-small text-ink-subtle">
            <ShieldCheck aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
            {data.redaction_notice} Sensitive values are removed before anything is stored,
            embedded, or sent to a language model.
          </p>
        )}

        <Divider className="my-5" />

        <KeyValueGrid
          columns={4}
          entries={[
            { label: "IOMETE version", value: data.iomete_version || "—" },
            { label: "Environment", value: data.environment || "—" },
            { label: "Deployment", value: data.deployment_model || "—" },
            { label: "Kubernetes", value: data.kubernetes_distribution || "—" },
          ]}
        />
      </Card>

      {/* ------------------------------------------------------------- Replay */}
      {execution ? (
        <ReplayRunner
          execution={execution}
          onFinished={() => {
            void ticket.reload();
            void executions.reload();
          }}
        />
      ) : (
        <>
          {similar.loading && !similar.data && (
            <LoadingState label="Searching prior resolutions" />
          )}
          {similar.error && !similar.data && (
            <ErrorState error={similar.error} onRetry={similar.reload} compact />
          )}
          {similar.data && (
            <>
              {similar.data.playbook_matches.some(
                (match) => match.gate_status === "clean",
              ) && <ReplayIntro stepCount={similar.data.playbook_matches[0]?.playbook.step_count ?? 0} />}
              <SimilarMatches
                ticketId={ticketId}
                initial={similar.data}
                canRunReplay={canRunReplay}
                onReplayStarted={(execution) => {
                  setStarted(execution);
                  void executions.reload();
                }}
              />
            </>
          )}
        </>
      )}

      {/* ------------------------------------------------------------ History */}
      <Tabs
        persistKey="ticket.history"
        items={[
          { id: "events", label: "Activity", icon: <Inbox />, count: data.events.length },
          {
            id: "replays",
            label: "Past replays",
            count: executions.data?.results.length ?? 0,
          },
        ]}
      >
        {(tab) => (
          <>
            {tab === "events" && (
              <ol className="space-y-2.5">
                {[...data.events]
                  .sort(
                    (a, b) =>
                      new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
                  )
                  .map((event) => (
                    <li
                      key={event.id}
                      className="rounded-md border border-border bg-surface-raised p-3.5"
                    >
                      <div className="flex flex-wrap items-baseline justify-between gap-2.5">
                        <span className="text-small font-medium text-ink">
                          {event.event_type_label}
                        </span>
                        <span className="text-[11px] text-ink-subtle">
                          {formatDateTime(event.created_at)}
                        </span>
                      </div>
                      {event.body && (
                        <p className="mt-1.5 whitespace-pre-wrap text-small text-ink-muted">
                          {event.body}
                        </p>
                      )}
                      {event.author_name && (
                        <p className="mt-1.5 text-[11px] text-ink-subtle">
                          {event.author_name}
                        </p>
                      )}
                    </li>
                  ))}
              </ol>
            )}

            {tab === "replays" && (
              <>
                {(executions.data?.results.length ?? 0) === 0 ? (
                  <p className="flex items-start gap-2 text-small text-ink-subtle">
                    <FileWarning aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
                    No replay has been run on this ticket yet.
                  </p>
                ) : (
                  <DetailList>
                    {(executions.data?.results ?? []).map((item) => (
                      <DetailRow key={item.id} label={item.playbook_title}>
                        {item.status_label} · {item.steps_completed}/{item.total_steps}{" "}
                        steps · {relativeTime(item.created_at)}
                      </DetailRow>
                    ))}
                  </DetailList>
                )}
              </>
            )}
          </>
        )}
      </Tabs>
    </div>
  );
}
