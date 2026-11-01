"use client";

import * as React from "react";

import {
  BarChart3,
  Briefcase,
  Building2,
  MessageCircleQuestion,
  ShieldCheck,
  TriangleAlert,
  Wrench,
} from "lucide-react";

import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { Persona, PersonaSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

import {
  AsyncRegion,
  Badge,
  Card,
  Eyebrow,
  Skeleton,
  SkeletonText,
  SourceList,
} from "@/components/ui";

const PERSONA_ICONS: Record<string, React.ReactNode> = {
  cto: <Building2 />,
  "data-engineer": <Wrench />,
  "data-analyst": <BarChart3 />,
  "security-compliance": <ShieldCheck />,
  business: <Briefcase />,
};

/**
 * Role-tailored explanation.
 *
 * The same platform explained five different ways, because the thing a compliance lead
 * needs to hear is not the thing a data engineer needs to hear, and a single page written
 * for "everyone" ends up written for nobody.
 *
 * Points flagged `caveat` by the knowledge base are rendered with a visible marker rather
 * than quietly mixed in. Those are the honest trade-offs — "self-hosting means you own the
 * operations", "these are vendor claims, verify them" — and they are the reason this reads
 * as an assessment rather than a brochure.
 */
export function PersonaExplorer({ personas }: { personas: PersonaSummary[] }) {
  const [selected, setSelected] = React.useState<string | null>(null);

  const persona = useResource<Persona>(
    () => api.persona(selected ?? ""),
    [selected],
    { enabled: Boolean(selected) },
  );

  return (
    <div className="space-y-7">
      <fieldset>
        <legend className="sr-only">Choose your role</legend>
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {personas.map((option) => {
            const active = selected === option.id;
            return (
              <button
                key={option.id}
                type="button"
                aria-pressed={active}
                onClick={() => setSelected(active ? null : option.id)}
                className={cn(
                  "flex items-start gap-3 rounded-lg border p-4 text-left",
                  "transition-[border-color,background-color,transform] duration-150",
                  active
                    ? "border-accent-500 bg-accent-50 shadow-subtle"
                    : "border-border bg-surface-raised hover:-translate-y-0.5 hover:border-border-strong hover:shadow-subtle",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "mt-0.5 grid size-8 shrink-0 place-items-center rounded-md [&>svg]:size-4",
                    active
                      ? "bg-accent-200 text-accent-800 dark:text-accent-200"
                      : "bg-surface-inset text-ink-subtle",
                  )}
                >
                  {PERSONA_ICONS[option.id] ?? <Briefcase />}
                </span>
                <span className="min-w-0">
                  <span className="block text-small font-medium text-ink">{option.label}</span>
                  <span className="mt-0.5 block text-small text-ink-muted">{option.short}</span>
                </span>
              </button>
            );
          })}
        </div>
      </fieldset>

      {!selected && (
        <Card tone="sunken" className="text-center">
          <p className="text-small text-ink-muted">
            Pick a role above. You will get the same platform explained in the terms that
            role actually cares about — including the questions worth putting to an IOMETE
            sales engineer.
          </p>
        </Card>
      )}

      {selected && (
        <AsyncRegion
          loading={persona.loading}
          error={persona.error}
          data={persona.data}
          onRetry={persona.reload}
          skeleton={
            <Card className="space-y-4">
              <Skeleton className="h-5 w-48" />
              <SkeletonText lines={3} />
              <Skeleton className="h-24 w-full" rounded="lg" />
            </Card>
          }
        >
          {(data) => <PersonaDetail persona={data} />}
        </AsyncRegion>
      )}
    </div>
  );
}

function PersonaDetail({ persona }: { persona: Persona }) {
  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-wrap items-center gap-2.5">
          <span
            aria-hidden="true"
            className="grid size-8 place-items-center rounded-md bg-accent-100 text-accent-700 [&>svg]:size-4 dark:text-accent-300"
          >
            {PERSONA_ICONS[persona.id] ?? <Briefcase />}
          </span>
          <Eyebrow as="h3">Explained for a {persona.label.toLowerCase()}</Eyebrow>
        </div>
        <p className="mt-4 text-[1.0625rem] leading-relaxed text-ink measure">
          {persona.opening}
        </p>

        {persona.cares_about.length > 0 && (
          <div className="mt-6 border-t border-border pt-5">
            <Eyebrow as="h4">What you are probably weighing</Eyebrow>
            <ul className="mt-3 grid gap-2 sm:grid-cols-2">
              {persona.cares_about.map((item) => (
                <li key={item} className="flex items-start gap-2.5 text-small">
                  <span
                    aria-hidden="true"
                    className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent-500"
                  />
                  <span className="text-ink-muted">{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      <div className="space-y-3">
        {persona.key_points.map((point) => (
          <Card
            key={point.title}
            tone={point.caveat ? "sunken" : "raised"}
            className={cn(point.caveat && "border-caution/30")}
          >
            <div className="flex items-start gap-3">
              {point.caveat && (
                <span
                  aria-hidden="true"
                  className="mt-0.5 shrink-0 text-caution [&>svg]:size-[18px]"
                >
                  <TriangleAlert />
                </span>
              )}
              <div className="min-w-0">
                <h4 className="flex flex-wrap items-center gap-2 text-h3 text-ink">
                  {point.title}
                  {point.caveat && (
                    <Badge tone="caution" size="sm">
                      Honest trade-off
                    </Badge>
                  )}
                </h4>
                <p className="mt-2 text-small text-ink-muted measure">{point.body}</p>
                {point.sources.length > 0 && (
                  <div className="mt-3">
                    <SourceList sources={point.sources} inline label="source" />
                  </div>
                )}
              </div>
            </div>
          </Card>
        ))}
      </div>

      {persona.questions_to_ask_iomete.length > 0 && (
        <Card tone="inverse">
          <div className="flex items-start gap-3">
            <span
              aria-hidden="true"
              className="mt-0.5 shrink-0 text-accent-400 [&>svg]:size-[18px]"
            >
              <MessageCircleQuestion />
            </span>
            <div className="min-w-0">
              <h4 className="text-h3 text-ink-inverse">
                Take these to an IOMETE sales engineer
              </h4>
              <p className="mt-1.5 text-small text-ink-inverse-muted">
                Questions COMPASS cannot answer from public documentation — which is
                precisely why they are worth asking.
              </p>
              <ol className="mt-4 space-y-2.5">
                {persona.questions_to_ask_iomete.map((question, index) => (
                  <li key={question} className="flex items-start gap-3">
                    <span
                      aria-hidden="true"
                      className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-graphite-800 text-[11px] font-semibold text-accent-400"
                    >
                      {index + 1}
                    </span>
                    <span className="text-small text-ink-inverse-muted">{question}</span>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
