import { ArrowDown } from "lucide-react";

import type { PipelineStage } from "@/lib/types";

import { Card, Eyebrow } from "@/components/ui";

/**
 * The journey from raw data to an answer.
 *
 * Seven stages, each naming the IOMETE component that does the work and citing the
 * documentation it was read from. The point of the list is to make a lakehouse legible to
 * someone who has only ever seen a database: it is not one box, it is a sequence, and the
 * sequence is where the cost and the governance live.
 */
export function PipelineStages({ stages }: { stages: PipelineStage[] }) {
  const ordered = [...stages].sort((a, b) => a.order - b.order);

  return (
    <ol className="space-y-0">
      {ordered.map((stage, index) => (
        <li key={stage.id}>
          <Card tone="flat" className="relative">
            <div className="flex items-start gap-4">
              <span
                aria-hidden="true"
                className="grid size-7 shrink-0 place-items-center rounded-full bg-accent-600 text-[11px] font-semibold text-white"
              >
                {stage.order}
              </span>
              <div className="min-w-0 flex-1">
                <h3 className="text-h3 text-ink">{stage.title}</h3>
                <p className="mt-1.5 text-small text-ink-muted measure">{stage.summary}</p>
                <p className="mt-2.5 text-[11px] uppercase tracking-wide text-accent-700 dark:text-accent-400">
                  {stage.iomete_component}
                </p>
              </div>
            </div>
          </Card>
          {index < ordered.length - 1 && (
            <div aria-hidden="true" className="flex justify-center py-1.5">
              <ArrowDown className="size-4 text-ink-subtle" />
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}

/** The same stages as a compact horizontal strip, for a page that already has a diagram. */
export function PipelineStrip({ stages }: { stages: PipelineStage[] }) {
  const ordered = [...stages].sort((a, b) => a.order - b.order);
  return (
    <div className="scroll-fade-r -mx-1 overflow-x-auto px-1 pb-1">
      <ol className="flex min-w-max items-stretch gap-2">
        {ordered.map((stage) => (
          <li
            key={stage.id}
            className="w-44 shrink-0 rounded-md border border-border bg-surface-raised p-3"
          >
            <Eyebrow as="h3">Step {stage.order}</Eyebrow>
            <p className="mt-1 text-small font-medium text-ink">{stage.title}</p>
            <p className="mt-1 text-[11px] leading-snug text-ink-subtle">
              {stage.iomete_component}
            </p>
          </li>
        ))}
      </ol>
    </div>
  );
}
