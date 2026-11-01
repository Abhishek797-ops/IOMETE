import Link from "next/link";

import {
  ArrowRight,
  BookOpenCheck,
  CircleHelp,
  Database,
  GitBranch,
  Layers,
  Lock,
  Route,
  Search,
  ShieldCheck,
  Sparkles,
  Terminal,
  Workflow,
} from "lucide-react";

import { api } from "@/lib/api";
import type { ProductKnowledge } from "@/lib/types";

import { PublicSection } from "@/components/layout/PublicShell";
import {
  Badge,
  Button,
  Card,
  ClaimStatusBadge,
  Eyebrow,
  SourceList,
} from "@/components/ui";

export const metadata = {
  title: "IOMETE COMPASS — Understand. Experience. Resolve. Improve.",
};

/**
 * The landing page.
 *
 * A server component. The product knowledge is fetched at render time and cached, so the
 * page's factual content comes from the same source-backed knowledge base as everything
 * else — the taglines and technology descriptions below are not copy someone typed into
 * a template.
 *
 * If the API is unreachable the page still renders: the hero and the narrative are
 * structural, and only the sourced fact strip degrades. A landing page that 500s because
 * a backend is down is a bad trade.
 */
export default async function LandingPage() {
  let knowledge: ProductKnowledge | null = null;
  try {
    knowledge = await api.productKnowledge();
  } catch {
    knowledge = null;
  }

  return (
    <>
      <Hero knowledge={knowledge} />
      <TwoProblems />
      <Differentiator />
      <HowItWorks />
      <TechnologyStrip knowledge={knowledge} />
      <Honesty knowledge={knowledge} />
      <ClosingCta />
    </>
  );
}

// =====================================================================================
// Hero
// =====================================================================================

function Hero({ knowledge }: { knowledge: ProductKnowledge | null }) {
  const positioning = knowledge?.positioning;

  return (
    <div className="relative overflow-hidden border-b border-border">
      <div
        aria-hidden="true"
        className="dot-grid dot-grid-fade pointer-events-none absolute inset-0 opacity-60"
      />
      <PublicSection width="wide" className="relative pb-16 pt-16 sm:pb-20 sm:pt-24">
        <div className="grid items-start gap-12 lg:grid-cols-[1.05fr_0.95fr] lg:gap-16">
          <div>
            <Badge tone="accent" icon={<Sparkles />}>
              Enablement &amp; support intelligence for IOMETE
            </Badge>

            <h1 className="mt-6 text-display text-ink">
              Understand it. Try it.
              <br />
              <span className="text-accent-700 dark:text-accent-400">Fix it once.</span>
            </h1>

            <p className="mt-6 max-w-xl text-[1.0625rem] leading-relaxed text-ink-muted">
              IOMETE is a sovereign data lakehouse — warehouse-grade SQL and AI workloads
              over one open copy of your data, running inside infrastructure you control.
              COMPASS makes it understandable to evaluate, and makes its support history
              compound instead of repeating.
            </p>

            {positioning && (
              <figure className="mt-7 border-l-2 border-accent-400 pl-4">
                <blockquote className="text-body italic text-ink">
                  “{positioning.one_liner}”
                </blockquote>
                <figcaption className="mt-2 flex flex-wrap items-center gap-2 text-small text-ink-subtle">
                  IOMETE’s own description
                  <ClaimStatusBadge status={positioning.status} />
                  <SourceList sources={positioning.sources} inline label="from" />
                </figcaption>
              </figure>
            )}

            <div className="mt-9 flex flex-wrap gap-3">
              <Link href="/explore">
                <Button variant="primary" size="lg" iconRight={<ArrowRight />}>
                  Explain IOMETE to me
                </Button>
              </Link>
              <Link href="/fit-finder">
                <Button variant="secondary" size="lg">
                  Check if it fits us
                </Button>
              </Link>
            </div>

            <p className="mt-4 text-small text-ink-subtle">
              No sign-up needed. The Fit Finder works anonymously and publishes the rubric
              it scores you against.
            </p>
          </div>

          <div className="lg:pt-6">
            <JourneyCards />
          </div>
        </div>
      </PublicSection>
    </div>
  );
}

function JourneyCards() {
  const journeys = [
    {
      href: "/explore",
      icon: <BookOpenCheck />,
      title: "Explore IOMETE",
      body:
        "What a data lakehouse actually is, what makes IOMETE sovereign, and how Spark, " +
        "Iceberg and Kubernetes fit together — explained for your role.",
      meta: "11 questions · 5 roles",
    },
    {
      href: "/architecture",
      icon: <Layers />,
      title: "Architecture playground",
      body:
        "An interactive map of the platform. Click any component to see what it does, " +
        "why it is needed, and what you get from it — with a link to the documentation.",
      meta: "20 documented components",
    },
    {
      href: "/lakehouse-playground",
      icon: <Terminal />,
      title: "Lakehouse playground",
      body:
        "Write your own SQL against a synthetic retail dataset and get real results, " +
        "plus an illustrated view of the stages a distributed engine goes through.",
      meta: "Real SQL · 36k rows",
    },
  ];

  return (
    <ul className="space-y-3">
      {journeys.map((journey) => (
        <li key={journey.href}>
          <Link href={journey.href} className="block rounded-lg">
            <Card interactive className="group">
              <div className="flex items-start gap-4">
                <span
                  aria-hidden="true"
                  className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-md bg-accent-50 text-accent-700 [&>svg]:size-[18px] dark:text-accent-300"
                >
                  {journey.icon}
                </span>
                <div className="min-w-0">
                  <h2 className="flex items-center gap-1.5 text-h3 text-ink">
                    {journey.title}
                    <ArrowRight
                      aria-hidden="true"
                      className="size-4 text-ink-subtle transition-transform duration-200 group-hover:translate-x-0.5"
                    />
                  </h2>
                  <p className="mt-1.5 text-small text-ink-muted">{journey.body}</p>
                  <p className="mt-2.5 text-micro uppercase text-ink-subtle">{journey.meta}</p>
                </div>
              </div>
            </Card>
          </Link>
        </li>
      ))}
    </ul>
  );
}

// =====================================================================================
// The two problems
// =====================================================================================

function TwoProblems() {
  return (
    <PublicSection width="wide" className="py-16 sm:py-20">
      <div className="max-w-2xl">
        <Eyebrow as="h2">Why this exists</Eyebrow>
        <h3 className="mt-3 text-h1 text-ink">Two problems, one platform</h3>
        <p className="mt-4 text-body text-ink-muted measure">
          A sophisticated infrastructure product is hard to buy and hard to support, for
          related reasons: the thing being explained is genuinely complex, and the
          knowledge needed to operate it stays locked in individual engineers’ heads.
        </p>
      </div>

      <div className="mt-10 grid gap-5 lg:grid-cols-2">
        <Card className="flex flex-col">
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden="true"
              className="grid size-8 place-items-center rounded-md bg-info-soft text-info [&>svg]:size-4"
            >
              <CircleHelp />
            </span>
            <Eyebrow as="h4">Problem one</Eyebrow>
          </div>
          <h4 className="mt-3 text-h2 text-ink">
            Nobody buys what they cannot picture
          </h4>
          <p className="mt-3 text-small text-ink-muted">
            A prospect arrives not knowing what a lakehouse is, why they would want one, or
            whether this one fits the infrastructure they already run. A features page does
            not answer any of that — and a slide deck answers it for whoever wrote the deck,
            not for the security lead who has to sign off.
          </p>
          <ul className="mt-5 space-y-2.5 text-small">
            {[
              "Concepts explained in plain language, with analogies that hold up",
              "The same architecture explained differently for a CTO, an engineer, an analyst and a compliance lead",
              "An indicative fit assessment with a published rubric — including where IOMETE is the wrong answer",
              "A working lakehouse you can type SQL into, not a screenshot",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2.5">
                <span
                  aria-hidden="true"
                  className="mt-1.5 size-1.5 shrink-0 rounded-full bg-info"
                />
                <span className="text-ink-muted">{item}</span>
              </li>
            ))}
          </ul>
          <div className="mt-6 flex flex-wrap gap-2 pt-1">
            <Link href="/explore">
              <Button variant="secondary" size="sm" iconRight={<ArrowRight />}>
                Explore
              </Button>
            </Link>
            <Link href="/fit-finder">
              <Button variant="ghost" size="sm">
                Fit Finder
              </Button>
            </Link>
          </div>
        </Card>

        <Card className="flex flex-col">
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden="true"
              className="grid size-8 place-items-center rounded-md bg-accent-50 text-accent-700 [&>svg]:size-4 dark:text-accent-300"
            >
              <GitBranch />
            </span>
            <Eyebrow as="h4">Problem two</Eyebrow>
          </div>
          <h4 className="mt-3 text-h2 text-ink">
            The same investigation, over and over
          </h4>
          <p className="mt-3 text-small text-ink-muted">
            A Forward Deployed Engineer spends three hours proving that a Spark executor was
            killed because a skewed partition exceeded its memory limit. Six weeks later a
            different customer hits the same thing, and someone spends three hours proving
            it again. The investigation happened; the knowledge did not survive it.
          </p>
          <ul className="mt-5 space-y-2.5 text-small">
            {[
              "Hybrid retrieval over real support history — exact error signatures, not just text similarity",
              "A guided, branching workflow that collects evidence before it suggests a change",
              "Every resolved investigation becomes a reviewed, versioned playbook",
              "An escalation that arrives with the diagnostics already done",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2.5">
                <span
                  aria-hidden="true"
                  className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent-500"
                />
                <span className="text-ink-muted">{item}</span>
              </li>
            ))}
          </ul>
          <div className="mt-6 flex flex-wrap gap-2 pt-1">
            <Link href="/login">
              <Button variant="secondary" size="sm" iconRight={<ArrowRight />}>
                See the support workspace
              </Button>
            </Link>
          </div>
        </Card>
      </div>
    </PublicSection>
  );
}

// =====================================================================================
// The differentiator
// =====================================================================================

function Differentiator() {
  return (
    <div className="border-y border-border bg-surface-sunken">
      <PublicSection width="wide" className="py-16 sm:py-20">
        <div className="grid gap-12 lg:grid-cols-[0.95fr_1.05fr] lg:gap-16">
          <div>
            <Eyebrow as="h2">The difference</Eyebrow>
            <h3 className="mt-3 text-h1 text-ink">
              Resolution Replay, then knowledge that compounds
            </h3>
            <p className="mt-4 text-body text-ink-muted measure">
              Most support AI is a chat box over a document store. It answers confidently,
              cites nothing you can check, and knows nothing more tomorrow than it did
              today. COMPASS is built the other way round.
            </p>

            <dl className="mt-8 space-y-6">
              <div>
                <dt className="flex items-center gap-2 text-h3 text-ink">
                  <Route aria-hidden="true" className="size-[18px] text-accent-600" />
                  Turn-by-turn, not a wall of text
                </dt>
                <dd className="mt-2 text-small text-ink-muted measure">
                  A verified playbook becomes a branching workflow: look at this, tell us
                  what you saw, and the route recalculates. A step that could change a
                  running cluster is unreachable until the evidence justifies it — and then
                  it needs an explicit approval from someone authorised, with the blast
                  radius spelled out.
                </dd>
              </div>
              <div>
                <dt className="flex items-center gap-2 text-h3 text-ink">
                  <Workflow aria-hidden="true" className="size-[18px] text-accent-600" />
                  Every investigation leaves something behind
                </dt>
                <dd className="mt-2 text-small text-ink-muted measure">
                  When an FDE resolves a ticket, COMPASS drafts a reusable playbook from what
                  actually happened. An engineer reviews it, redacts anything
                  customer-specific, sets which versions and environments it applies to, and
                  approves it. Only then can it be offered to anyone — and the next customer
                  with that error resolves it themselves.
                </dd>
              </div>
              <div>
                <dt className="flex items-center gap-2 text-h3 text-ink">
                  <Search aria-hidden="true" className="size-[18px] text-accent-600" />
                  Three questions, three answers
                </dt>
                <dd className="mt-2 text-small text-ink-muted measure">
                  “Do these look alike?”, “is it the same cause?” and “will this fix work
                  here?” are different questions. COMPASS scores them separately, because
                  collapsing them into one match percentage is how an engineer ends up
                  applying the wrong fix to production with confidence.
                </dd>
              </div>
            </dl>
          </div>

          <ReplayPreview />
        </div>
      </PublicSection>
    </div>
  );
}

/**
 * A static illustration of a Resolution Replay session.
 *
 * Hand-drawn in markup rather than a screenshot: it stays sharp, respects dark mode, and
 * is readable by a screen reader. The numbers shown are illustrative and the card says so.
 */
function ReplayPreview() {
  return (
    <Card tone="raised" className="overflow-hidden p-0">
      <div className="border-b border-border bg-surface-sunken px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <p className="text-small font-medium text-ink">
            Resolution Replay — illustrative
          </p>
          <Badge tone="verified" size="sm" icon={<ShieldCheck />}>
            Verified playbook
          </Badge>
        </div>
      </div>

      <div className="divide-y divide-border">
        <PreviewStep
          index={1}
          title="Confirm the executor was killed for memory"
          body="Reason: OOMKilled with exit code 137 — not Evicted."
          state="done"
          kind="Read-only"
        />
        <PreviewStep
          index={2}
          title="Check whether a few tasks do most of the work"
          body="Max task input 14.2 GB against a median of 310 MB. Clear skew."
          state="done"
          kind="Read-only"
        />
        <PreviewStep
          index={3}
          title="Raise executor memory and enable skew handling"
          body="Restarts the compute cluster. Running queries will be interrupted."
          state="gated"
          kind="Needs approval"
        />
        <PreviewStep
          index={4}
          title="Re-run the failing workload"
          body="Completing the steps is not evidence. This is."
          state="pending"
          kind="Verification"
        />
      </div>

      <div className="border-t border-border bg-surface-sunken px-4 py-3">
        <p className="text-small text-ink-subtle">
          COMPASS never runs anything against your cluster. Commands are shown for you to
          run, and the record of what you observed becomes the escalation if it does not work.
        </p>
      </div>
    </Card>
  );
}

function PreviewStep({
  index,
  title,
  body,
  state,
  kind,
}: {
  index: number;
  title: string;
  body: string;
  state: "done" | "gated" | "pending";
  kind: string;
}) {
  return (
    <div className="flex gap-3.5 px-4 py-3.5">
      <span
        aria-hidden="true"
        className={
          state === "done"
            ? "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-positive-soft text-[11px] font-semibold text-positive"
            : state === "gated"
              ? "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-caution-soft text-[11px] font-semibold text-caution"
              : "mt-0.5 grid size-6 shrink-0 place-items-center rounded-full border border-border-strong text-[11px] font-semibold text-ink-subtle"
        }
      >
        {state === "done" ? "✓" : index}
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-small font-medium text-ink">{title}</p>
          <Badge
            tone={state === "gated" ? "caution" : "neutral"}
            size="sm"
            icon={state === "gated" ? <Lock /> : undefined}
          >
            {kind}
          </Badge>
        </div>
        <p className="mt-1 text-small text-ink-muted">{body}</p>
      </div>
    </div>
  );
}

// =====================================================================================
// How it works
// =====================================================================================

function HowItWorks() {
  const steps = [
    {
      title: "A problem is described",
      body:
        "Credentials and personal data are stripped before anything is stored. Error " +
        "codes, symptoms and the affected component are extracted automatically.",
    },
    {
      title: "History is searched four ways",
      body:
        "Semantic similarity, keyword matching, exact error-signature fingerprints and " +
        "structured metadata — fused, then gated on product version and environment.",
    },
    {
      title: "A verified fix is offered, or it escalates",
      body:
        "If an approved playbook applies, it runs as a guided workflow. If nothing " +
        "applies, that is an escalation — said plainly rather than guessed at.",
    },
    {
      title: "The investigation becomes knowledge",
      body:
        "A reviewed, versioned playbook that the next customer with that error can follow " +
        "themselves. That is the whole point.",
    },
  ];

  return (
    <PublicSection width="wide" className="py-16 sm:py-20">
      <div className="max-w-2xl">
        <Eyebrow as="h2">The loop</Eyebrow>
        <h3 className="mt-3 text-h1 text-ink">How a ticket becomes a playbook</h3>
      </div>

      <ol className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {steps.map((step, index) => (
          <li key={step.title}>
            <Card tone="flat" className="h-full border-t-2 border-t-accent-400">
              <span className="text-micro uppercase text-accent-700 dark:text-accent-400">
                Step {index + 1}
              </span>
              <h4 className="mt-2 text-h3 text-ink">{step.title}</h4>
              <p className="mt-2 text-small text-ink-muted">{step.body}</p>
            </Card>
          </li>
        ))}
      </ol>
    </PublicSection>
  );
}

// =====================================================================================
// Technologies
// =====================================================================================

function TechnologyStrip({ knowledge }: { knowledge: ProductKnowledge | null }) {
  if (!knowledge) return null;

  const featured = ["apache-spark", "apache-iceberg", "kubernetes", "apache-ranger"];
  const technologies = featured
    .map((id) => knowledge.technologies.find((technology) => technology.id === id))
    .filter((technology): technology is NonNullable<typeof technology> => Boolean(technology));

  if (technologies.length === 0) return null;

  return (
    <div className="border-y border-border bg-graphite-950 text-ink-inverse">
      <PublicSection width="wide" className="py-16 sm:py-20">
        <div className="max-w-2xl">
          <Eyebrow as="h2" className="text-accent-400">
            Built on
          </Eyebrow>
          <h3 className="mt-3 text-h1 text-ink-inverse">
            Open source, in your own environment
          </h3>
          <p className="mt-4 text-body text-ink-inverse-muted measure">
            Nothing proprietary holds your data. Tables are Apache Iceberg in object storage
            you own, which means another engine can read them and a migration away does not
            start with an export.
          </p>
        </div>

        <dl className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {technologies.map((technology) => (
            <div
              key={technology.id}
              className="rounded-lg border border-graphite-800 bg-graphite-900 p-5"
            >
              <dt className="flex items-start justify-between gap-3">
                <span className="text-h3 text-ink-inverse">{technology.name}</span>
                <Database
                  aria-hidden="true"
                  className="mt-1 size-4 shrink-0 text-ink-inverse-subtle"
                />
              </dt>
              <dd className="mt-1 text-micro uppercase text-accent-400">{technology.role}</dd>
              <dd className="mt-3 text-small text-ink-inverse-muted">
                {technology.plain_english}
              </dd>
              <dd className="mt-3">
                <SourceList sources={technology.sources} inline label="source" />
              </dd>
            </div>
          ))}
        </dl>

        <div className="mt-8">
          <Link href="/architecture">
            <Button variant="primary" iconRight={<ArrowRight />}>
              See how it fits together
            </Button>
          </Link>
        </div>
      </PublicSection>
    </div>
  );
}

// =====================================================================================
// Honesty
// =====================================================================================

function Honesty({ knowledge }: { knowledge: ProductKnowledge | null }) {
  return (
    <PublicSection width="wide" className="py-16 sm:py-20">
      <div className="grid gap-10 lg:grid-cols-[1fr_1fr] lg:gap-14">
        <div>
          <Eyebrow as="h2">What we will not tell you</Eyebrow>
          <h3 className="mt-3 text-h1 text-ink">
            Every claim here has a source, or a label
          </h3>
          <p className="mt-4 text-body text-ink-muted measure">
            COMPASS makes statements about someone else’s product, so it holds itself to a
            rule: anything presented as fact was read from official IOMETE documentation and
            links to the page it came from. Anything that could not be verified says so
            instead of being quietly dropped or quietly asserted.
          </p>
          {knowledge && (
            <div className="mt-6 flex flex-wrap gap-2">
              <Badge tone="verified">
                {knowledge.capabilities.filter((c) => c.status === "verified").length}{" "}
                documented capabilities
              </Badge>
              <Badge tone="unverified">
                {
                  knowledge.capabilities.filter((c) => c.status === "needs_confirmation")
                    .length
                }{" "}
                need confirmation
              </Badge>
              <Badge tone="neutral">{knowledge.sources.length} sources, dated</Badge>
            </div>
          )}
        </div>

        <Card tone="sunken">
          <h4 className="text-h3 text-ink">COMPASS does not claim</h4>
          <ul className="mt-4 space-y-2.5">
            {(
              knowledge?.do_not_claim ?? [
                "Any specific pricing figure, discount or contract term.",
                "Named IOMETE customers, logos or case-study outcomes.",
                "Quantified cost savings for a specific prospect’s workload.",
                "Performance benchmarks, query latency figures or throughput numbers.",
                "Service level agreements, uptime guarantees or support response times.",
              ]
            )
              .slice(0, 6)
              .map((item) => (
                <li key={item} className="flex items-start gap-2.5 text-small">
                  <span
                    aria-hidden="true"
                    className="mt-1.5 size-1.5 shrink-0 rounded-full bg-critical"
                  />
                  <span className="text-ink-muted">{item}</span>
                </li>
              ))}
          </ul>
          <p className="mt-5 text-small text-ink-subtle">
            IOMETE’s own marketing claims 2–5× cost savings on one page and 2–3× on another.
            COMPASS reports both as vendor claims and notes that they disagree, rather than
            repeating whichever is more flattering.
          </p>
        </Card>
      </div>
    </PublicSection>
  );
}

// =====================================================================================
// Closing
// =====================================================================================

function ClosingCta() {
  return (
    <PublicSection width="wide" className="pb-20">
      <Card tone="raised" className="relative overflow-hidden border-accent-200 p-0">
        <div
          aria-hidden="true"
          className="dot-grid pointer-events-none absolute inset-0 opacity-40"
        />
        <div className="relative grid gap-8 p-8 sm:p-10 lg:grid-cols-[1.4fr_1fr] lg:items-center">
          <div>
            <h2 className="text-h1 text-ink">Start wherever you are</h2>
            <p className="mt-3 text-body text-ink-muted measure">
              Not sure what a lakehouse is? Start with the explainer. Know exactly what you
              need? Run the Fit Finder and take the report to your architecture review.
              Already a customer with a failing cluster? Sign in and let COMPASS search what
              has already been solved.
            </p>
          </div>
          <div className="flex flex-col gap-2.5">
            <Link href="/explore">
              <Button variant="primary" size="lg" fullWidth iconRight={<ArrowRight />}>
                Explain IOMETE to me
              </Button>
            </Link>
            <Link href="/fit-finder">
              <Button variant="secondary" size="lg" fullWidth>
                Run the Fit Finder
              </Button>
            </Link>
            <Link href="/request-demo">
              <Button variant="ghost" size="lg" fullWidth>
                Talk to the IOMETE team
              </Button>
            </Link>
          </div>
        </div>
      </Card>
    </PublicSection>
  );
}
