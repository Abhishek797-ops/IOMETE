import Link from "next/link";

import { ArrowRight, Layers, Terminal } from "lucide-react";

import { api } from "@/lib/api";
import type { ExplainerPayload } from "@/lib/types";

import { PublicSection } from "@/components/layout/PublicShell";
import { ConceptComparison } from "@/components/features/knowledge/ConceptComparison";
import { PersonaExplorer } from "@/components/features/knowledge/PersonaExplorer";
import {
  Badge,
  Button,
  Card,
  ClaimStatusBadge,
  ClaimStatusLegend,
  Disclosure,
  ErrorState,
  Eyebrow,
  SourceList,
} from "@/components/ui";

export const metadata = {
  title: "Explore IOMETE",
  description:
    "What a data lakehouse is, what makes IOMETE sovereign, and how Spark, Iceberg and " +
    "Kubernetes fit together — in plain language, with every claim sourced.",
};

/**
 * The explainer.
 *
 * A server component: the content is static, source-backed knowledge, so it is fetched
 * and cached at render rather than streamed to the browser as JSON and re-rendered there.
 * The only client island is the persona selector, which fetches on demand.
 *
 * The page is built to be read by someone with no data-engineering background. That is
 * the whole requirement, and it shapes the order: concepts before technologies, analogies
 * before architecture, and the honest trade-off stated rather than buried.
 */
export default async function ExplorePage() {
  let explainer: ExplainerPayload | null = null;
  let failure: Error | null = null;
  try {
    explainer = await api.explainer();
  } catch (caught) {
    failure = caught instanceof Error ? caught : new Error("Unknown error");
  }

  if (!explainer) {
    return (
      <PublicSection className="py-20">
        <ErrorState
          error={failure ?? new Error("The explainer could not be loaded.")}
        />
      </PublicSection>
    );
  }

  const { positioning, concepts, questions, technologies, personas, status_legend } =
    explainer;

  const starters = questions.filter((question) =>
    ["q1", "q2", "q5", "q6"].includes(question.id),
  );
  const technical = questions.filter((question) =>
    ["q7", "q8", "q9"].includes(question.id),
  );
  const practical = questions.filter((question) =>
    ["q10", "q11"].includes(question.id),
  );

  return (
    <>
      {/* ---------------------------------------------------------------- Hero */}
      <div className="border-b border-border bg-surface-sunken">
        <PublicSection width="wide" className="py-14 sm:py-18">
          <div className="max-w-3xl">
            <Eyebrow as="h1">Understand</Eyebrow>
            <h2 className="mt-3 text-h1 text-ink sm:text-display">
              What IOMETE actually is
            </h2>
            <p className="mt-5 text-[1.0625rem] leading-relaxed text-ink-muted">
              No prior data-engineering knowledge assumed. We will start with what a
              lakehouse is and why anyone wants one, then get specific about what IOMETE
              does and what it asks of you in return.
            </p>

            {positioning && (
              <div className="mt-7 flex flex-wrap items-center gap-2.5">
                <Badge tone="accent">{positioning.tagline}</Badge>
                <ClaimStatusBadge status={positioning.status} />
                <SourceList sources={positioning.sources} inline label="source" />
              </div>
            )}
          </div>
        </PublicSection>
      </div>

      {/* ------------------------------------------------- The three concepts */}
      <PublicSection width="wide" className="py-14 sm:py-18" id="concepts">
        <div className="max-w-2xl">
          <Eyebrow as="h2">Start here</Eyebrow>
          <h3 className="mt-3 text-h1 text-ink">Lake, warehouse, lakehouse</h3>
          <p className="mt-4 text-body text-ink-muted measure">
            Three words that get used interchangeably and mean quite different things. The
            difference is the entire reason this category exists, so it is worth two
            minutes.
          </p>
        </div>
        <div className="mt-9">
          <ConceptComparison concepts={concepts} />
        </div>
      </PublicSection>

      {/* ------------------------------------------------------- The questions */}
      <div className="border-y border-border bg-surface-sunken">
        <PublicSection width="wide" className="py-14 sm:py-18" id="questions">
          <div className="max-w-2xl">
            <Eyebrow as="h2">The obvious questions</Eyebrow>
            <h3 className="mt-3 text-h1 text-ink">
              Answered plainly, with the source
            </h3>
            <p className="mt-4 text-body text-ink-muted measure">
              Every answer below was written from official IOMETE documentation and links
              to the page it came from. Where something could not be verified, it says so
              rather than being smoothed over.
            </p>
          </div>

          <div className="mt-9 grid gap-8 lg:grid-cols-[1fr_20rem] lg:gap-12">
            <div className="space-y-8">
              <QuestionGroup title="The basics" questions={starters} defaultOpenFirst />
              <QuestionGroup title="How it works" questions={technical} />
              <QuestionGroup title="In practice" questions={practical} />
            </div>

            <aside className="space-y-5 lg:sticky lg:top-24 lg:self-start">
              <ClaimStatusLegend legend={status_legend} />
              <Card tone="raised">
                <Eyebrow as="h3">Next steps</Eyebrow>
                <div className="mt-3 space-y-2.5">
                  <Link href="/architecture" className="block">
                    <Button
                      variant="secondary"
                      fullWidth
                      icon={<Layers />}
                      className="justify-start"
                    >
                      See the architecture
                    </Button>
                  </Link>
                  <Link href="/lakehouse-playground" className="block">
                    <Button
                      variant="secondary"
                      fullWidth
                      icon={<Terminal />}
                      className="justify-start"
                    >
                      Try a lakehouse
                    </Button>
                  </Link>
                  <Link href="/fit-finder" className="block">
                    <Button variant="primary" fullWidth iconRight={<ArrowRight />}>
                      Check if it fits us
                    </Button>
                  </Link>
                </div>
              </Card>
            </aside>
          </div>
        </PublicSection>
      </div>

      {/* ------------------------------------------------------- Technologies */}
      <PublicSection width="wide" className="py-14 sm:py-18" id="technologies">
        <div className="max-w-2xl">
          <Eyebrow as="h2">The moving parts</Eyebrow>
          <h3 className="mt-3 text-h1 text-ink">
            What each piece of open source is doing
          </h3>
          <p className="mt-4 text-body text-ink-muted measure">
            IOMETE is assembled from well-known open source rather than a proprietary
            engine. That matters for two reasons: the skills are transferable, and the data
            is readable by other tools.
          </p>
        </div>

        <dl className="mt-9 grid gap-4 md:grid-cols-2">
          {technologies.map((technology) => (
            <Card key={technology.id} tone="flat" className="h-full">
              <dt>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <span className="text-h3 text-ink">{technology.name}</span>
                  <ClaimStatusBadge status={technology.status} />
                </div>
                <span className="mt-1 block text-micro uppercase text-accent-700 dark:text-accent-400">
                  {technology.role}
                </span>
              </dt>
              <dd className="mt-3 text-small text-ink-muted">{technology.plain_english}</dd>
              {technology.iomete_usage && (
                <dd className="mt-3 border-t border-border pt-3 text-small text-ink-muted">
                  <span className="font-medium text-ink">In IOMETE: </span>
                  {technology.iomete_usage}
                </dd>
              )}
              {technology.documented_properties &&
                technology.documented_properties.length > 0 && (
                  <dd className="mt-3 flex flex-wrap gap-1.5">
                    {technology.documented_properties.map((property) => (
                      <Badge key={property} tone="neutral" size="sm">
                        {property}
                      </Badge>
                    ))}
                  </dd>
                )}
              <dd className="mt-3">
                <SourceList sources={technology.sources} inline label="source" />
              </dd>
            </Card>
          ))}
        </dl>
      </PublicSection>

      {/* ------------------------------------------------------------ Personas */}
      <div className="border-y border-border bg-surface-sunken">
        <PublicSection width="wide" className="py-14 sm:py-18" id="personas">
          <div className="max-w-2xl">
            <Eyebrow as="h2">For your role</Eyebrow>
            <h3 className="mt-3 text-h1 text-ink">
              The same platform, explained five ways
            </h3>
            <p className="mt-4 text-body text-ink-muted measure">
              A CTO is weighing lock-in and operational risk. A compliance lead wants to
              know where the data physically sits and who can prove it. An analyst wants to
              know whether their dashboard will still work. Pick yours.
            </p>
          </div>
          <div className="mt-9">
            <PersonaExplorer personas={personas} />
          </div>
        </PublicSection>
      </div>

      {/* ------------------------------------------------------------- Closing */}
      <PublicSection width="wide" className="py-14 sm:py-18">
        <Card tone="raised" className="border-accent-200">
          <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr] lg:items-center">
            <div>
              <h2 className="text-h1 text-ink">Now see whether it fits</h2>
              <p className="mt-3 text-body text-ink-muted measure">
                The Fit Finder scores your situation against a published rubric and tells
                you plainly where IOMETE is the wrong answer — including when a managed
                service would serve you better.
              </p>
            </div>
            <div className="flex flex-col gap-2.5">
              <Link href="/fit-finder">
                <Button variant="primary" size="lg" fullWidth iconRight={<ArrowRight />}>
                  Run the Fit Finder
                </Button>
              </Link>
              <Link href="/architecture">
                <Button variant="secondary" size="lg" fullWidth>
                  Explore the architecture
                </Button>
              </Link>
            </div>
          </div>
        </Card>
      </PublicSection>
    </>
  );
}

function QuestionGroup({
  title,
  questions,
  defaultOpenFirst,
}: {
  title: string;
  questions: ExplainerPayload["questions"];
  defaultOpenFirst?: boolean;
}) {
  if (questions.length === 0) return null;
  return (
    <section>
      <Eyebrow as="h3">{title}</Eyebrow>
      <div className="mt-3 space-y-2.5">
        {questions.map((question, index) => (
          <Disclosure
            key={question.id}
            defaultOpen={defaultOpenFirst && index === 0}
            summary={<span className="text-body text-ink">{question.question}</span>}
          >
            <p className="text-small leading-relaxed text-ink-muted measure">
              {question.answer}
            </p>
            {question.sources.length > 0 && (
              <div className="mt-3.5 border-t border-border pt-3">
                <SourceList sources={question.sources} />
              </div>
            )}
          </Disclosure>
        ))}
      </div>
    </section>
  );
}
