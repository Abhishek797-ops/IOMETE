"use client";

import * as React from "react";

import {
  AlertTriangle,
  Ban,
  CircleHelp,
  ClipboardList,
  Lightbulb,
  MessageSquareQuote,
  Printer,
  RotateCcw,
  Timer,
  Wand2,
} from "lucide-react";

import { api } from "@/lib/api";
import { useMutation, useResource } from "@/lib/hooks";
import type {
  BriefObjection,
  BriefQuestion,
  BriefStatus,
  CallBrief,
  CallPrepOptions,
} from "@/lib/types";
import { cn, percent } from "@/lib/utils";

import {
  Badge,
  Button,
  Card,
  ChipMultiSelect,
  Disclosure,
  Divider,
  Eyebrow,
  FormError,
  Input,
  Select,
  SkeletonText,
  SourceList,
  Tabs,
  TagInput,
} from "@/components/ui";

const SIZES = [
  { value: "small", label: "Small — under 200 people" },
  { value: "medium", label: "Medium — 200 to 1,000" },
  { value: "large", label: "Large — 1,000 to 10,000" },
  { value: "enterprise", label: "Enterprise — over 10,000" },
  { value: "unknown", label: "I do not know" },
];

const STACK_SUGGESTIONS = [
  "Snowflake",
  "Databricks",
  "BigQuery",
  "Redshift",
  "Hadoop",
  "Spark",
  "Kubernetes",
  "OpenShift",
  "Apache Iceberg",
  "Kafka",
  "Power BI",
  "Tableau",
  "Looker",
  "Oracle",
  "SQL Server",
  "Teradata",
  "PostgreSQL",
  "S3",
  "Azure Data Lake Storage Gen2",
];

/**
 * How each provenance level is shown.
 *
 * Deliberately four visually distinct treatments rather than a single "AI generated"
 * caveat. A rep skimming this fifteen minutes before a call needs to tell, at a glance,
 * which lines they can say out loud and which they must not.
 */
const STATUS_PRESENTATION: Record<
  BriefStatus,
  { label: string; tone: "verified" | "caution" | "unverified" | "gated" | "neutral" }
> = {
  verified: { label: "Sourced", tone: "verified" },
  vendor_claim: { label: "IOMETE's own claim", tone: "caution" },
  needs_confirmation: { label: "Needs confirming", tone: "unverified" },
  industry_concept: { label: "Industry concept", tone: "neutral" },
  assumed: { label: "Assumed from your inputs", tone: "unverified" },
  unknown: { label: "Not documented", tone: "gated" },
};

function StatusChip({ status }: { status: BriefStatus }) {
  const presentation = STATUS_PRESENTATION[status] ?? STATUS_PRESENTATION.unknown;
  return (
    <Badge tone={presentation.tone} size="sm">
      {presentation.label}
    </Badge>
  );
}

/**
 * The call-prep generator.
 *
 * The friction: a sales engineer has fifteen minutes before a call with a company they
 * have not researched. They do not need IOMETE explained to them — they need a prepared
 * position, and more importantly they need to know which parts of it are safe to say.
 *
 * What makes this more than a prompt with a form in front of it is that every line
 * carries its provenance, and the lines COMPASS cannot substantiate are **counted rather
 * than written around**. The headline number on the result is the unknown rate: the
 * proportion of the likely conversation that public documentation does not answer. A rep
 * who knows that figure before walking in is better prepared than one handed a brief that
 * answers everything and is confidently wrong about a third of it.
 */
export function CallPrep() {
  const options = useResource<CallPrepOptions>(async () => api.callPrepOptions(), []);

  const [form, setForm] = React.useState({
    company_name: "",
    industry: "financial_services",
    company_size: "enterprise",
    meeting_type: "discovery",
  });
  const [stack, setStack] = React.useState<string[]>([]);
  const [personas, setPersonas] = React.useState<string[]>([]);
  const [touched, setTouched] = React.useState(false);
  const [brief, setBrief] = React.useState<CallBrief | null>(null);

  const briefRef = React.useRef<HTMLDivElement>(null);

  const generate = useMutation(
    async () =>
      api.callPrep({
        ...form,
        known_stack: stack,
        attendee_personas: personas,
      }),
    {
      onSuccess: (result) => {
        setBrief(result);
        requestAnimationFrame(() =>
          briefRef.current?.scrollIntoView({ block: "start", behavior: "smooth" }),
        );
      },
    },
  );

  const onSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (!form.company_name.trim()) return;
    void generate.run();
  };

  const set = (key: keyof typeof form) => (
    event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>,
  ) => setForm((current) => ({ ...current, [key]: event.target.value }));

  return (
    <div className="space-y-8">
      {/* --------------------------------------------------------------- Form */}
      <Card className="print:hidden">
        <Eyebrow as="h2">Before the call</Eyebrow>
        <h3 className="mt-2 text-h2 text-ink">
          Tell us what you know. We will be honest about the rest.
        </h3>
        <p className="mt-2 text-small text-ink-muted measure">
          Five fields, fifteen seconds. Anything you leave blank comes back as an explicit
          assumption or an unknown — it is never quietly filled in.
        </p>

        <form onSubmit={onSubmit} className="mt-6 space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Input
              label="Company"
              required
              value={form.company_name}
              onChange={set("company_name")}
              placeholder="e.g. Northwind Bank"
              error={
                touched && !form.company_name.trim() ? "Who is the call with?" : null
              }
            />
            <Select
              label="Industry"
              options={options.data?.industries ?? []}
              value={form.industry}
              onChange={set("industry")}
            />
            <Select
              label="Roughly how big?"
              options={SIZES}
              value={form.company_size}
              onChange={set("company_size")}
            />
            <Select
              label="What kind of call?"
              options={options.data?.meeting_types ?? []}
              value={form.meeting_type}
              onChange={set("meeting_type")}
            />
          </div>

          <TagInput
            label="What do you know they run?"
            description="Changes what the brief expects to be asked. Leave it blank and the brief will say so."
            placeholder="e.g. Snowflake"
            values={stack}
            onChange={setStack}
            suggestions={STACK_SUGGESTIONS}
          />

          {options.data && (
            <ChipMultiSelect
              label="Who is in the room?"
              description="Each role brings its own questions — including the ones IOMETE does not publish answers to."
              options={options.data.personas.map((persona) => ({
                value: persona.value,
                label: persona.label,
              }))}
              values={personas}
              onChange={setPersonas}
            />
          )}

          <FormError error={generate.error} />

          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={generate.pending}
              icon={<Wand2 />}
            >
              Build my brief
            </Button>
            {brief && (
              <Button
                variant="ghost"
                onClick={() => {
                  setBrief(null);
                  generate.reset();
                }}
                icon={<RotateCcw />}
              >
                Clear
              </Button>
            )}
          </div>
        </form>
      </Card>

      {options.loading && !options.data && <SkeletonText lines={3} />}

      {/* -------------------------------------------------------------- Brief */}
      {brief && (
        <div ref={briefRef}>
          <BriefView brief={brief} />
        </div>
      )}
    </div>
  );
}

function BriefView({ brief }: { brief: CallBrief }) {
  const headingRef = React.useRef<HTMLHeadingElement>(null);
  React.useEffect(() => {
    headingRef.current?.focus();
  }, []);

  const { coverage } = brief;

  return (
    <div className="space-y-6">
      {/* ------------------------------------------------------------ Headline */}
      <Card tone="raised" className="border-accent-200">
        <div className="flex flex-wrap items-start justify-between gap-5">
          <div className="min-w-[16rem] flex-1">
            <Eyebrow>Call brief</Eyebrow>
            <h2
              ref={headingRef}
              tabIndex={-1}
              className="mt-1.5 text-h1 text-ink focus-visible:outline-none"
            >
              {brief.headline}
            </h2>
            <p className="mt-3 text-small text-ink-subtle">
              Brief {brief.brief_version} · built from IOMETE&rsquo;s public documentation
              and what you typed. No language model was involved.
            </p>
          </div>

          {/* The honesty metric, given the most prominent position on the page. */}
          <div className="w-full max-w-xs shrink-0 rounded-lg border border-border bg-surface-sunken p-4">
            <p className="text-micro uppercase text-ink-subtle">
              What we could not answer
            </p>
            <p className="mt-1.5 flex items-baseline gap-2">
              <span className="text-[2rem] font-semibold leading-none tabular text-ink">
                {percent(coverage.unknown_rate)}
              </span>
              <span className="text-small text-ink-subtle">of the brief</span>
            </p>
            <dl className="mt-3.5 space-y-1">
              {[
                { label: "Sourced to IOMETE docs", value: coverage.sourced, tone: "text-positive" },
                { label: "Not documented", value: coverage.unknown, tone: "text-ink-muted" },
                { label: "Assumed from your inputs", value: coverage.assumed, tone: "text-caution" },
              ].map((row) => (
                <div key={row.label} className="flex items-baseline justify-between gap-2">
                  <dt className="text-[11px] text-ink-subtle">{row.label}</dt>
                  <dd className={cn("text-small tabular font-medium", row.tone)}>
                    {row.value}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>

        <p className="mt-4 text-[11px] leading-snug text-ink-subtle">{coverage.note}</p>

        <Divider className="my-5" />

        <div className="flex flex-wrap items-center gap-2.5 print:hidden">
          <Button variant="secondary" onClick={() => window.print()} icon={<Printer />}>
            Print or save as PDF
          </Button>
          <span className="text-small text-ink-subtle">
            Cited: {brief.cited_sources.join(", ") || "—"}
          </span>
        </div>
      </Card>

      {/* ------------------------------------------------------------- Opening */}
      <Card>
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-md bg-accent-50 text-accent-700 [&>svg]:size-[18px] dark:text-accent-300"
          >
            <MessageSquareQuote />
          </span>
          <div className="min-w-0">
            <Eyebrow as="h3">How to open</Eyebrow>
            <p className="mt-2 text-body leading-relaxed text-ink measure">
              &ldquo;{brief.opening}&rdquo;
            </p>
          </div>
        </div>

        {brief.qualifying_questions.length > 0 && (
          <>
            <Divider className="my-5" />
            <Eyebrow as="h3">Establish in the first five minutes</Eyebrow>
            <ol className="mt-3 space-y-2.5">
              {brief.qualifying_questions.map((question, index) => (
                <li key={question} className="flex items-start gap-3">
                  <span
                    aria-hidden="true"
                    className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-surface-inset text-[11px] font-semibold text-ink-muted"
                  >
                    {index + 1}
                  </span>
                  <span className="text-small text-ink-muted">{question}</span>
                </li>
              ))}
            </ol>
          </>
        )}
      </Card>

      {/* ---------------------------------------------------------- Do not say */}
      <Card className="border-critical/30 bg-critical-soft">
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-md bg-surface-raised text-critical [&>svg]:size-[18px]"
          >
            <Ban />
          </span>
          <div className="min-w-0">
            <Eyebrow as="h3">Do not say</Eyebrow>
            <p className="mt-1.5 text-small text-ink-muted measure">
              These are the claims that cost deals at the technical evaluation, not in the
              meeting. They travel with every brief because the moment you most need them
              is the moment you are improvising an answer.
            </p>
            <ul className="mt-3.5 space-y-2">
              {brief.do_not_say.map((item) => (
                <li key={item} className="flex items-start gap-2.5">
                  <Ban
                    aria-hidden="true"
                    className="mt-0.5 size-3.5 shrink-0 text-critical"
                  />
                  <span className="text-small text-ink-muted">{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Card>

      {/* ---------------------------------------------------------------- Tabs */}
      <Tabs
        persistKey="callprep.tab"
        items={[
          {
            id: "questions",
            label: "They will ask",
            icon: <CircleHelp />,
            count: brief.likely_questions.length,
          },
          {
            id: "objections",
            label: "Objections",
            icon: <AlertTriangle />,
            count: brief.objections.length,
          },
          {
            id: "lead",
            label: "Lead with",
            icon: <Lightbulb />,
            count: brief.lead_with.length,
          },
          {
            id: "unknowns",
            label: "Take back to IOMETE",
            icon: <Timer />,
            count: brief.unknowns.length,
          },
          {
            id: "assumptions",
            label: "What we assumed",
            icon: <ClipboardList />,
            count: brief.assumptions.length + brief.stack_signals.length,
          },
        ]}
      >
        {(tab) => (
          <>
            {tab === "questions" && (
              <ul className="space-y-3">
                {brief.likely_questions.map((question) => (
                  <li key={question.question}>
                    <QuestionCard question={question} />
                  </li>
                ))}
              </ul>
            )}

            {tab === "objections" && (
              <ul className="space-y-3">
                {brief.objections.map((objection) => (
                  <li key={objection.id}>
                    <ObjectionCard objection={objection} />
                  </li>
                ))}
              </ul>
            )}

            {tab === "lead" && (
              <div className="space-y-4">
                <p className="text-small text-ink-muted measure">
                  Verified capabilities only, chosen for this sector. Each one carries the
                  limitation IOMETE documents alongside it — stating the limit yourself is
                  what makes the rest credible.
                </p>
                <ul className="space-y-3">
                  {brief.lead_with.map((capability) => (
                    <li key={capability.name}>
                      <Card tone="flat">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                          <h4 className="text-small font-medium text-ink">
                            {capability.name}
                          </h4>
                          <StatusChip status={capability.status} />
                        </div>
                        <p className="mt-2 text-small text-ink-muted">
                          {capability.why_now}
                        </p>
                        {capability.limitation && (
                          <p className="mt-2 rounded-md bg-surface-sunken px-3 py-2 text-small text-ink-muted">
                            <span className="font-medium text-ink">
                              Say this too:{" "}
                            </span>
                            {capability.limitation}
                          </p>
                        )}
                        {capability.sources.length > 0 && (
                          <div className="mt-2.5">
                            <SourceList
                              sources={capability.sources}
                              inline
                              label="source"
                            />
                          </div>
                        )}
                      </Card>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {tab === "unknowns" && (
              <div className="space-y-4">
                <p className="text-small text-ink-muted measure">
                  {brief.unknowns.length} questions public documentation does not answer.
                  COMPASS will not invent an answer for any of them. Saying &ldquo;I will
                  find out&rdquo; costs you nothing; a guess that is wrong costs you the
                  technical evaluation.
                </p>
                <ol className="space-y-3">
                  {brief.unknowns.map((unknown, index) => (
                    <li
                      key={`${unknown.question}-${index}`}
                      className="rounded-md border border-gated/30 bg-gated-soft p-3.5"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2.5">
                        <p className="text-small font-medium text-ink">
                          {unknown.question}
                        </p>
                        <Badge tone="gated" size="sm">
                          {unknown.asked_by}
                        </Badge>
                      </div>
                      <p className="mt-1.5 text-small text-ink-muted">{unknown.why}</p>
                    </li>
                  ))}
                </ol>
              </div>
            )}

            {tab === "assumptions" && (
              <div className="space-y-6">
                <div>
                  <Eyebrow as="h3">What you told us</Eyebrow>
                  <dl className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-2">
                    {brief.inputs_given.map((input) => (
                      <div key={input.label} className="flex flex-wrap gap-x-2">
                        <dt className="text-small text-ink-subtle">{input.label}:</dt>
                        <dd className="text-small text-ink">{input.value}</dd>
                      </div>
                    ))}
                  </dl>
                </div>

                {brief.stack_signals.length > 0 && (
                  <div>
                    <Eyebrow as="h3">What their stack implies</Eyebrow>
                    <ul className="mt-3 space-y-3">
                      {brief.stack_signals.map((signal) => (
                        <li key={signal.signal}>
                          <Card tone="flat">
                            <div className="flex flex-wrap items-start justify-between gap-2.5">
                              <p className="text-small font-medium text-ink">
                                {signal.signal}
                              </p>
                              <StatusChip status={signal.status} />
                            </div>
                            <p className="mt-1.5 text-[11px] text-ink-subtle">
                              matched on: {signal.matched_on.join(", ")}
                            </p>
                            <p className="mt-2 text-small text-ink-muted">
                              {signal.implication}
                            </p>
                            <p className="mt-2 text-small text-ink">
                              <span className="text-ink-subtle">Ask: </span>
                              {signal.ask}
                            </p>
                          </Card>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div>
                  <Eyebrow as="h3">Assumptions about this sector</Eyebrow>
                  <p className="mt-1.5 text-small text-ink-muted measure">
                    These are inferences from the industry you picked, not research about
                    this company. Verify them in the first five minutes.
                  </p>
                  <ul className="mt-3 space-y-2">
                    {brief.assumptions.map((assumption) => (
                      <li
                        key={assumption.text}
                        className="flex flex-wrap items-start gap-2.5 rounded-md border border-border bg-surface-raised px-3.5 py-2.5"
                      >
                        <StatusChip status={assumption.status} />
                        <span className="min-w-[12rem] flex-1 text-small text-ink-muted">
                          {assumption.text}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </>
        )}
      </Tabs>

      <p className="text-[11px] leading-relaxed text-ink-subtle measure">
        {brief.disclaimer}
      </p>
    </div>
  );
}

function QuestionCard({ question }: { question: BriefQuestion }) {
  const unknown = question.status === "unknown";
  return (
    <Card tone={unknown ? "flat" : "raised"} className={cn(unknown && "border-gated/30")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h4 className="min-w-[14rem] flex-1 text-small font-medium text-ink">
          {question.question}
        </h4>
        <div className="flex shrink-0 flex-wrap gap-2">
          <StatusChip status={question.status} />
          {question.asked_by !== "any" && (
            <Badge tone="neutral" size="sm">
              {question.asked_by}
            </Badge>
          )}
        </div>
      </div>
      <p
        className={cn(
          "mt-2.5 text-small measure",
          unknown ? "text-ink-subtle" : "text-ink-muted",
        )}
      >
        {question.answer}
      </p>
      {question.sources.length > 0 && (
        <div className="mt-2.5">
          <SourceList sources={question.sources} inline label="source" />
        </div>
      )}
    </Card>
  );
}

function ObjectionCard({ objection }: { objection: BriefObjection }) {
  return (
    <Card tone="flat">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h4 className="min-w-[14rem] flex-1 text-small font-medium text-ink">
          &ldquo;{objection.objection}&rdquo;
        </h4>
        <StatusChip status={objection.status} />
      </div>
      <p className="mt-2.5 text-small text-ink-muted measure">{objection.position}</p>
      <div className="mt-3">
        <Disclosure
          summary={<span className="text-small text-ink-muted">If they press</span>}
        >
          <p className="text-small text-ink-muted measure">{objection.if_pressed}</p>
        </Disclosure>
      </div>
      {objection.sources.length > 0 && (
        <div className="mt-2.5">
          <SourceList sources={objection.sources} inline label="source" />
        </div>
      )}
    </Card>
  );
}
