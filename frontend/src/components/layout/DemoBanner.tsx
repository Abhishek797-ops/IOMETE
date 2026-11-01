"use client";


import { FlaskConical, X } from "lucide-react";

import { api } from "@/lib/api";
import { useResource, useSessionDismissal } from "@/lib/hooks";
import type { IntegrationModeReport, SystemStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

import { IconButton } from "@/components/ui";

/**
 * The deployment-honesty banner.
 *
 * It states, on every page, what is actually real here: that the support history is
 * synthetic, which AI provider produced any generated text, and which integrations are
 * simulated. Dismissible per session, because someone demoing for an hour should not have
 * to look at it the whole time — but it returns on the next visit, and the detail stays
 * available from the footer and `/admin/integrations`.
 *
 * All of it comes from `/api/v1/system/status/`. Nothing here is hardcoded, so the banner
 * cannot claim demo mode when the deployment is live, or the reverse.
 */
export function DemoBanner({ tone = "light" }: { tone?: "light" | "dark" }) {
  const { data } = useResource<SystemStatus>(() => api.systemStatus(), []);
  const [dismissed, dismiss] = useSessionDismissal("demoBanner");

  if (!data || dismissed) return null;

  const simulated = Object.entries(data.integrations)
    .filter(
      (entry): entry is [string, IntegrationModeReport] =>
        typeof entry[1] === "object" && entry[1] !== null && "is_simulated" in entry[1],
    )
    .filter(([, report]) => report.is_simulated)
    .map(([name]) => name);

  const notices: string[] = [];
  if (data.demo_mode) notices.push(data.demo_mode_notice);
  if (!data.ai.llm_live) notices.push(data.ai.notice);
  if (simulated.length > 0) {
    notices.push(
      `${simulated.map((name) => name.toUpperCase()).join(" and ")} ${
        simulated.length === 1 ? "is" : "are"
      } simulated — no external system is contacted.`,
    );
  }

  if (notices.length === 0) return null;

  return (
    <div
      role="status"
      className={cn(
        "border-b",
        tone === "dark"
          ? "border-graphite-800 bg-graphite-900 text-ink-inverse-muted"
          : "border-simulated/20 bg-simulated-soft text-ink-muted",
      )}
    >
      <div className="mx-auto flex max-w-[86rem] items-start gap-3 px-4 py-2.5 sm:px-6 lg:px-8">
        <FlaskConical
          aria-hidden="true"
          className={cn(
            "mt-0.5 size-4 shrink-0",
            tone === "dark" ? "text-simulated" : "text-simulated",
          )}
        />
        <div className="min-w-0 flex-1 text-small leading-snug">
          <span className="font-medium">Demonstration deployment.</span>{" "}
          {notices.join(" ")}
        </div>
        <IconButton
          label="Dismiss this notice for this session"
          size="sm"
          onClick={dismiss}
          className={cn(
            "-mr-2 -mt-1 shrink-0",
            tone === "dark" && "text-ink-inverse-subtle hover:bg-graphite-800",
          )}
        >
          <X />
        </IconButton>
      </div>
    </div>
  );
}
