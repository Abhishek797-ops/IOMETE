import { ArrowRight, Boxes, Library, Lock } from "lucide-react";

import type { Concept } from "@/lib/types";
import { cn } from "@/lib/utils";

import { Badge, Card, ClaimStatusBadge, Eyebrow, SourceList } from "@/components/ui";

/**
 * The lake / warehouse / lakehouse explanation.
 *
 * Laid out as three columns that build on each other rather than three independent
 * cards, because the point is the progression: a lake is cheap and unreliable, a
 * warehouse is reliable and expensive, a lakehouse is the attempt to have both. Showing
 * them side by side with their weaknesses stated is what makes the third column mean
 * anything.
 *
 * Every analogy comes from the knowledge base, so the same warehouse-of-boxes metaphor
 * is used consistently across the whole product rather than being reinvented per page.
 */
export function ConceptComparison({ concepts }: { concepts: Concept[] }) {
  const order = ["data-lake", "data-warehouse", "data-lakehouse"];
  const ordered = order
    .map((id) => concepts.find((concept) => concept.id === id))
    .filter((concept): concept is Concept => Boolean(concept));

  const sovereignty = concepts.find((concept) => concept.id === "sovereignty");

  if (ordered.length === 0) return null;

  const icons: Record<string, React.ReactNode> = {
    "data-lake": <Boxes />,
    "data-warehouse": <Library />,
    "data-lakehouse": <Boxes />,
  };

  return (
    <div className="space-y-8">
      <div className="grid gap-4 lg:grid-cols-3">
        {ordered.map((concept, index) => {
          const isLakehouse = concept.id === "data-lakehouse";
          return (
            <div key={concept.id} className="relative">
              {/* The connector arrow, hidden on narrow layouts where the cards stack. */}
              {index < ordered.length - 1 && (
                <ArrowRight
                  aria-hidden="true"
                  className="absolute -right-[1.3rem] top-1/2 z-10 hidden size-5 -translate-y-1/2 text-border-strong lg:block"
                />
              )}
              <Card
                tone={isLakehouse ? "raised" : "flat"}
                className={cn(
                  "flex h-full flex-col",
                  isLakehouse && "border-accent-300 shadow-raised",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <span
                    aria-hidden="true"
                    className={cn(
                      "grid size-9 place-items-center rounded-md [&>svg]:size-[18px]",
                      isLakehouse
                        ? "bg-accent-100 text-accent-700 dark:text-accent-300"
                        : "bg-surface-inset text-ink-subtle",
                    )}
                  >
                    {icons[concept.id]}
                  </span>
                  {isLakehouse && <Badge tone="accent">What IOMETE is</Badge>}
                </div>

                <h3 className="mt-4 text-h2 text-ink">{concept.title}</h3>
                <p className="mt-3 text-small text-ink-muted">{concept.plain_english}</p>

                {concept.analogy && (
                  <p className="mt-4 border-l-2 border-border-strong pl-3 text-small italic text-ink-subtle">
                    {concept.analogy}
                  </p>
                )}

                <dl className="mt-5 space-y-3 border-t border-border pt-4">
                  {concept.strength && (
                    <div>
                      <dt className="text-micro uppercase text-positive">Good at</dt>
                      <dd className="mt-1 text-small text-ink-muted">{concept.strength}</dd>
                    </div>
                  )}
                  {concept.weakness && (
                    <div>
                      <dt className="text-micro uppercase text-caution">Bad at</dt>
                      <dd className="mt-1 text-small text-ink-muted">{concept.weakness}</dd>
                    </div>
                  )}
                </dl>

                {concept.iomete_note && (
                  <p className="mt-4 text-small text-ink-muted">
                    {concept.iomete_note}{" "}
                    <SourceList sources={concept.sources} inline label="source" />
                  </p>
                )}
              </Card>
            </div>
          );
        })}
      </div>

      {sovereignty && (
        <Card tone="inverse" className="overflow-hidden">
          <div className="grid gap-6 lg:grid-cols-[auto_1fr] lg:gap-8">
            <span
              aria-hidden="true"
              className="grid size-11 place-items-center rounded-lg bg-accent-900/50 text-accent-300 [&>svg]:size-5"
            >
              <Lock />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2.5">
                <Eyebrow as="h3" className="text-accent-400">
                  The part that matters most
                </Eyebrow>
                <ClaimStatusBadge status={sovereignty.status} />
              </div>
              <h3 className="mt-2 text-h2 text-ink-inverse">{sovereignty.title}</h3>
              <p className="mt-3 text-body text-ink-inverse-muted measure">
                {sovereignty.plain_english}
              </p>
              {sovereignty.analogy && (
                <p className="mt-3 border-l-2 border-graphite-700 pl-3 text-small italic text-ink-inverse-subtle">
                  {sovereignty.analogy}
                </p>
              )}

              {sovereignty.official_claims && sovereignty.official_claims.length > 0 && (
                <div className="mt-5">
                  <p className="text-micro uppercase text-ink-inverse-subtle">
                    IOMETE&rsquo;s own words
                  </p>
                  <ul className="mt-2 space-y-1.5">
                    {sovereignty.official_claims.map((claim) => (
                      <li key={claim} className="text-small text-ink-inverse-muted">
                        {claim}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {sovereignty.why_it_matters && (
                <p className="mt-5 text-small text-ink-inverse-muted measure">
                  <span className="font-medium text-ink-inverse">Why it matters: </span>
                  {sovereignty.why_it_matters}
                </p>
              )}

              <div className="mt-5">
                <SourceList sources={sovereignty.sources} inline label="read from" />
              </div>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
