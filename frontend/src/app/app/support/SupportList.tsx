"use client";

import * as React from "react";

import { useRouter } from "next/navigation";

import { Inbox, ShieldCheck } from "lucide-react";

import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { TicketListItem } from "@/lib/types";
import { relativeTime, severityTone, statusTone } from "@/lib/utils";

import {
  Badge,
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  Tabs,
} from "@/components/ui";

const FILTERS = [
  { id: "open", label: "Open" },
  { id: "all", label: "All" },
  { id: "resolved", label: "Resolved" },
];

const OPEN_STATUSES = new Set([
  "new",
  "triaging",
  "awaiting_customer",
  "in_progress",
  "escalated",
]);

/**
 * The customer's tickets.
 *
 * `has_approved_playbook` is surfaced as its own column because it is the one thing that
 * changes what the reader should do next: a ticket with a verified resolution waiting is
 * one they can close themselves, today, without an engineer.
 */
export function SupportList() {
  const router = useRouter();
  const [filter, setFilter] = React.useState("open");

  const tickets = useResource(async () => api.tickets(), []);

  if (tickets.loading && !tickets.data) return <LoadingState label="Loading your tickets" />;
  if (tickets.error && !tickets.data) {
    return <ErrorState error={tickets.error} onRetry={tickets.reload} />;
  }

  const all = tickets.data?.results ?? [];
  const rows = all.filter((ticket) => {
    if (filter === "open") return OPEN_STATUSES.has(ticket.status);
    if (filter === "resolved") return !OPEN_STATUSES.has(ticket.status);
    return true;
  });

  const withResolution = all.filter(
    (ticket) => OPEN_STATUSES.has(ticket.status) && ticket.has_approved_playbook,
  ).length;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Support"
        title="Your tickets"
        description={
          withResolution > 0
            ? `${withResolution} open ${withResolution === 1 ? "ticket has" : "tickets have"} a verified resolution ready to run.`
            : "Everything your organisation has raised with IOMETE."
        }
      />

      <Tabs items={FILTERS} value={filter} onChange={setFilter}>
        {() =>
          rows.length === 0 ? (
            <EmptyState
              icon={<Inbox />}
              title="Nothing here"
              description="No ticket matches this filter."
            />
          ) : (
            <DataTable<TicketListItem>
              caption="Your support tickets"
              rows={rows}
              rowKey={(ticket) => ticket.id}
              onRowClick={(ticket) => router.push(`/app/support/${ticket.id}`)}
              columns={[
                {
                  key: "reference",
                  header: "Ref",
                  mobileLabel: "Reference",
                  width: "9rem",
                  cell: (ticket) => (
                    <span className="font-mono text-[0.8125rem] text-ink-subtle">
                      {ticket.reference}
                    </span>
                  ),
                },
                {
                  key: "title",
                  header: "Problem",
                  mobileLabel: "Problem",
                  cell: (ticket) => (
                    <span className="font-medium text-ink">{ticket.title}</span>
                  ),
                },
                {
                  key: "resolution",
                  header: "Resolution",
                  mobileLabel: "Resolution",
                  cell: (ticket) =>
                    ticket.has_approved_playbook ? (
                      <span className="inline-flex items-center gap-1.5 text-small text-positive">
                        <ShieldCheck aria-hidden="true" className="size-3.5" />
                        Ready to run
                      </span>
                    ) : (
                      <span className="text-small text-ink-subtle">—</span>
                    ),
                },
                {
                  key: "severity",
                  header: "Severity",
                  mobileLabel: "Severity",
                  secondary: true,
                  cell: (ticket) => (
                    <Badge tone={severityTone(ticket.severity)} size="sm">
                      {ticket.severity_label}
                    </Badge>
                  ),
                },
                {
                  key: "status",
                  header: "Status",
                  mobileLabel: "Status",
                  cell: (ticket) => (
                    <Badge tone={statusTone(ticket.status)} size="sm">
                      {ticket.status_label}
                    </Badge>
                  ),
                },
                {
                  key: "age",
                  header: "Raised",
                  mobileLabel: "Raised",
                  align: "right",
                  secondary: true,
                  cell: (ticket) => (
                    <span className="text-small text-ink-subtle">
                      {relativeTime(ticket.created_at)}
                    </span>
                  ),
                },
              ]}
            />
          )
        }
      </Tabs>
    </div>
  );
}
