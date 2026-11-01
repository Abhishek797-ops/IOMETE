"use client";

import * as React from "react";

import {
  ArrowLeft,
  ArrowRight,
  Building2,
  Check,
  Gauge,
  Server,
  ShieldCheck,
  Sparkles,
  UserRound,
} from "lucide-react";

import { api } from "@/lib/api";
import { useMutation } from "@/lib/hooks";
import type { FitAnswers, FitAssessmentResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

import {
  Button,
  Card,
  Checkbox,
  ChipMultiSelect,
  Eyebrow,
  FormError,
  Input,
  RadioCardGroup,
  Select,
  TagInput,
} from "@/components/ui";

const CONSENT_TEXT =
  "I agree that IOMETE may contact me about this enquiry. My answers will be used to " +
  "prepare an indicative assessment and architecture recommendation.";

const EMPTY_ANSWERS: FitAnswers = {
  company_type: "",
  company_name: "",
  contact_role: "",
  persona: "",
  infrastructure_location: "",
  cloud_providers: [],
  current_systems: [],
  bi_tools: [],
  data_volume: "",
  primary_use_case: "",
  secondary_use_cases: [],
  sovereignty_requirement: "",
  challenges: [],
  current_architecture: "",
  constraints: [],
  kubernetes_maturity: "",
  team_size: "",
};

interface StepDefinition {
  id: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  /** Fields that must be answered before the step can be left. */
  required: (keyof FitAnswers)[];
}

const STEPS: StepDefinition[] = [
  {
    id: "about",
    title: "About you",
    description: "So the assessment speaks to the right concerns.",
    icon: <UserRound />,
    required: ["company_type"],
  },
  {
    id: "infrastructure",
    title: "Your infrastructure",
    description: "Where IOMETE would run, and what it would sit beside.",
    icon: <Server />,
    required: ["infrastructure_location"],
  },
  {
    id: "workload",
    title: "Scale and workload",
    description: "Whether a lakehouse is proportionate to what you have.",
    icon: <Gauge />,
    required: ["data_volume", "primary_use_case"],
  },
  {
    id: "requirements",
    title: "Requirements and pain",
    description: "What is driving the change, and what constrains it.",
    icon: <ShieldCheck />,
    required: ["sovereignty_requirement", "current_architecture"],
  },
  {
    id: "operations",
    title: "Operating it",
    description: "The part most assessments skip and most projects fail on.",
    icon: <Building2 />,
    required: ["kubernetes_maturity"],
  },
  {
    id: "contact",
    title: "Your report",
    description: "Optional. The assessment works without any of this.",
    icon: <Sparkles />,
    required: [],
  },
];

/**
 * The Fit Finder.
 *
 * Six steps over the ten discovery questions. Grouped rather than one-per-page because
 * ten separate screens feels like an interrogation, and the groupings are the ones a
 * person actually thinks in — infrastructure together, constraints together.
 *
 * Every question is answerable with "not sure", and the rubric handles missing data by
 * capping the band at "needs discussion" rather than guessing. That is why the form can
 * afford to be short: an honest partial answer is more useful than a forced one.
 */
export function FitFinderWizard({
  onComplete,
}: {
  onComplete: (result: FitAssessmentResponse) => void;
}) {
  const [stepIndex, setStepIndex] = React.useState(0);
  const [answers, setAnswers] = React.useState<FitAnswers>(EMPTY_ANSWERS);
  const [contact, setContact] = React.useState({ name: "", email: "" });
  const [consent, setConsent] = React.useState(false);
  const [touched, setTouched] = React.useState(false);

  const headingRef = React.useRef<HTMLHeadingElement>(null);

  const submit = useMutation(
    async () =>
      api.createFitAssessment({
        answers,
        ...(contact.name ? { contact_name: contact.name } : {}),
        ...(contact.email ? { contact_email: contact.email } : {}),
        consent_given: consent,
      }),
    { onSuccess: onComplete },
  );

  const step = STEPS[stepIndex]!;
  const isLast = stepIndex === STEPS.length - 1;

  const set = <K extends keyof FitAnswers>(key: K, value: FitAnswers[K]) => {
    setAnswers((current) => ({ ...current, [key]: value }));
  };

  const missing = step.required.filter((field) => {
    const value = answers[field];
    return Array.isArray(value) ? value.length === 0 : !value;
  });

  const advance = () => {
    setTouched(true);
    if (missing.length > 0) return;
    setTouched(false);
    if (isLast) {
      void submit.run();
      return;
    }
    setStepIndex((index) => Math.min(index + 1, STEPS.length - 1));
    // Move focus to the new step's heading so a keyboard or screen-reader user is told
    // where they now are, rather than being left on a button that changed meaning.
    requestAnimationFrame(() => headingRef.current?.focus());
  };

  const retreat = () => {
    setTouched(false);
    setStepIndex((index) => Math.max(index - 1, 0));
    requestAnimationFrame(() => headingRef.current?.focus());
  };

  const needsConsent = Boolean(contact.email || contact.name) && !consent;

  return (
    <div className="grid gap-6 lg:grid-cols-[16rem_1fr] lg:gap-10">
      {/* Step rail */}
      <nav aria-label="Assessment progress" className="lg:sticky lg:top-24 lg:self-start">
        <ol className="space-y-1">
          {STEPS.map((candidate, index) => {
            const state =
              index < stepIndex ? "done" : index === stepIndex ? "current" : "upcoming";
            return (
              <li key={candidate.id}>
                <button
                  type="button"
                  // Backwards only: jumping forward past a required answer would produce
                  // an assessment built on blanks.
                  disabled={index > stepIndex}
                  onClick={() => {
                    setTouched(false);
                    setStepIndex(index);
                  }}
                  aria-current={state === "current" ? "step" : undefined}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors",
                    state === "current" && "bg-accent-50",
                    state === "done" && "hover:bg-surface-sunken",
                    state === "upcoming" && "opacity-50",
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={cn(
                      "grid size-7 shrink-0 place-items-center rounded-full text-[11px] font-semibold [&>svg]:size-3.5",
                      state === "done" && "bg-positive-soft text-positive",
                      state === "current" && "bg-accent-600 text-white",
                      state === "upcoming" &&
                        "border border-border-strong text-ink-subtle",
                    )}
                  >
                    {state === "done" ? <Check /> : index + 1}
                  </span>
                  <span className="min-w-0">
                    <span
                      className={cn(
                        "block truncate text-small",
                        state === "current" ? "font-medium text-ink" : "text-ink-muted",
                      )}
                    >
                      {candidate.title}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        <p className="mt-4 px-3 text-small text-ink-subtle">
          Step {stepIndex + 1} of {STEPS.length}. Every question can be left as
          &ldquo;not sure&rdquo;.
        </p>
      </nav>

      {/* Step body */}
      <Card>
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-md bg-accent-50 text-accent-700 [&>svg]:size-[18px] dark:text-accent-300"
          >
            {step.icon}
          </span>
          <div className="min-w-0">
            <Eyebrow>Step {stepIndex + 1}</Eyebrow>
            <h2
              ref={headingRef}
              tabIndex={-1}
              className="mt-1 text-h2 text-ink focus-visible:outline-none"
            >
              {step.title}
            </h2>
            <p className="mt-1.5 text-small text-ink-muted">{step.description}</p>
          </div>
        </div>

        <div className="mt-7 space-y-7">
          {step.id === "about" && (
            <>
              <RadioCardGroup
                name="company_type"
                label="What kind of organisation are you?"
                required
                columns={2}
                value={answers.company_type as string}
                onChange={(value) => set("company_type", value)}
                error={touched && missing.includes("company_type") ? "Pick one to continue." : null}
                options={[
                  { value: "enterprise", label: "Large enterprise" },
                  { value: "mid_market", label: "Mid-market company" },
                  { value: "startup", label: "Startup or scale-up" },
                  { value: "public_sector", label: "Government or public sector" },
                  { value: "financial", label: "Financial services" },
                  { value: "healthcare", label: "Healthcare or life sciences" },
                  { value: "telecom", label: "Telecommunications" },
                  { value: "consultancy", label: "Consultancy or systems integrator" },
                  { value: "other", label: "Something else" },
                ]}
              />
              <div className="grid gap-4 sm:grid-cols-2">
                <Input
                  label="Organisation name"
                  hint="Optional"
                  value={answers.company_name ?? ""}
                  onChange={(event) => set("company_name", event.target.value)}
                  placeholder="Appears on your report"
                />
                <Input
                  label="Your role"
                  hint="Optional"
                  value={answers.contact_role ?? ""}
                  onChange={(event) => set("contact_role", event.target.value)}
                  placeholder="e.g. Head of Data Platform"
                />
              </div>
              <Select
                label="Which of these is closest to your perspective?"
                description="Shapes which trade-offs the assessment leads with."
                placeholder="Choose one"
                value={answers.persona ?? ""}
                onChange={(event) => set("persona", event.target.value)}
                options={[
                  { value: "cto", label: "Technology leadership — strategy, risk, cost" },
                  { value: "data-engineer", label: "Data engineering — pipelines and operations" },
                  { value: "data-analyst", label: "Analytics — getting answers out" },
                  { value: "security-compliance", label: "Security or compliance" },
                  { value: "business", label: "Business leadership — outcomes and risk" },
                ]}
              />
            </>
          )}

          {step.id === "infrastructure" && (
            <>
              <RadioCardGroup
                name="infrastructure_location"
                label="Where is your infrastructure hosted today?"
                description="IOMETE installs into a Kubernetes cluster you provide, so this is the first thing that matters."
                required
                columns={2}
                value={answers.infrastructure_location as string}
                onChange={(value) => set("infrastructure_location", value)}
                error={
                  touched && missing.includes("infrastructure_location")
                    ? "Pick one to continue."
                    : null
                }
                options={[
                  { value: "on_premises", label: "Entirely on-premises" },
                  { value: "public_cloud", label: "Public cloud" },
                  { value: "private_cloud", label: "Private cloud" },
                  { value: "hybrid", label: "Hybrid", hint: "On-premises and cloud together" },
                  {
                    value: "air_gapped",
                    label: "Air-gapped",
                    hint: "Isolated network with no outbound access",
                  },
                  { value: "undecided", label: "Not decided yet" },
                ]}
              />
              <ChipMultiSelect
                label="Which clouds do you use?"
                description="Determines the documented storage backend and scheduling behaviour."
                values={answers.cloud_providers}
                onChange={(values) => set("cloud_providers", values)}
                options={[
                  { value: "aws", label: "AWS" },
                  { value: "azure", label: "Azure" },
                  { value: "gcp", label: "Google Cloud" },
                  { value: "other", label: "Another provider" },
                ]}
              />
              <TagInput
                label="Which databases, storage and warehouses do you use today?"
                description="Only systems IOMETE actually documents an integration for will be credited."
                placeholder="e.g. PostgreSQL"
                values={answers.current_systems}
                onChange={(values) => set("current_systems", values)}
                suggestions={[
                  "PostgreSQL",
                  "MySQL",
                  "Oracle",
                  "SQL Server",
                  "Snowflake",
                  "BigQuery",
                  "Redshift",
                  "S3",
                  "MinIO",
                  "Apache Ozone",
                  "Azure Data Lake Storage Gen2",
                  "Kafka",
                  "Airflow",
                  "dbt",
                ]}
              />
              <TagInput
                label="Which BI and analysis tools must keep working?"
                placeholder="e.g. Power BI"
                values={answers.bi_tools}
                onChange={(values) => set("bi_tools", values)}
                suggestions={[
                  "Power BI",
                  "Tableau",
                  "Metabase",
                  "Apache Superset",
                  "Looker",
                  "Redash",
                  "Excel",
                ]}
              />
            </>
          )}

          {step.id === "workload" && (
            <>
              <RadioCardGroup
                name="data_volume"
                label="Roughly how much data do you process?"
                description="A lakehouse earns its complexity at scale. Below a terabyte, we will tell you so."
                required
                columns={2}
                value={answers.data_volume as string}
                onChange={(value) => set("data_volume", value)}
                error={touched && missing.includes("data_volume") ? "Pick one to continue." : null}
                options={[
                  { value: "under_1tb", label: "Under 1 TB" },
                  { value: "tb_1_10", label: "1–10 TB" },
                  { value: "tb_10_100", label: "10–100 TB" },
                  { value: "tb_100_1pb", label: "100 TB – 1 PB" },
                  { value: "over_1pb", label: "Over 1 PB" },
                  { value: "unknown", label: "Not sure" },
                ]}
              />
              <RadioCardGroup
                name="primary_use_case"
                label="What is the main thing you need it to do?"
                required
                columns={2}
                value={answers.primary_use_case as string}
                onChange={(value) => set("primary_use_case", value)}
                error={
                  touched && missing.includes("primary_use_case") ? "Pick one to continue." : null
                }
                options={[
                  {
                    value: "consolidation",
                    label: "Consolidate a lake and a warehouse",
                    hint: "Stop paying to store the same data twice",
                  },
                  { value: "bi_reporting", label: "BI and reporting" },
                  { value: "data_engineering", label: "Data engineering and ETL" },
                  { value: "real_time", label: "Real-time analytics" },
                  { value: "ai_ml", label: "AI and machine learning" },
                  { value: "data_science", label: "Data science and exploration" },
                  { value: "governance", label: "Governance and compliance reporting" },
                  { value: "data_mesh", label: "Data mesh / domain ownership" },
                  { value: "other", label: "Something else" },
                ]}
              />
              <ChipMultiSelect
                label="And what else, secondarily?"
                description="Several documented use cases on one platform is the consolidation argument."
                values={answers.secondary_use_cases}
                onChange={(values) => set("secondary_use_cases", values)}
                options={[
                  { value: "bi_reporting", label: "BI and reporting" },
                  { value: "data_engineering", label: "Data engineering" },
                  { value: "real_time", label: "Real-time analytics" },
                  { value: "ai_ml", label: "AI and ML" },
                  { value: "data_science", label: "Data science" },
                  { value: "governance", label: "Governance" },
                  { value: "consolidation", label: "Consolidation" },
                  { value: "data_mesh", label: "Data mesh" },
                ]}
              />
            </>
          )}

          {step.id === "requirements" && (
            <>
              <RadioCardGroup
                name="sovereignty_requirement"
                label="Do you have data sovereignty requirements?"
                description="The strongest single signal in the assessment, weighted highest in the rubric."
                required
                value={answers.sovereignty_requirement as string}
                onChange={(value) => set("sovereignty_requirement", value)}
                error={
                  touched && missing.includes("sovereignty_requirement")
                    ? "Pick one to continue."
                    : null
                }
                options={[
                  {
                    value: "mandatory",
                    label: "Mandatory",
                    hint: "Data cannot leave our control — law, regulator or policy",
                  },
                  { value: "strong", label: "Strong preference" },
                  { value: "some", label: "Some workloads only" },
                  { value: "none", label: "No specific requirement" },
                  { value: "unknown", label: "Not sure" },
                ]}
              />
              <RadioCardGroup
                name="current_architecture"
                label="What do you run today?"
                required
                columns={2}
                value={answers.current_architecture as string}
                onChange={(value) => set("current_architecture", value)}
                error={
                  touched && missing.includes("current_architecture")
                    ? "Pick one to continue."
                    : null
                }
                options={[
                  { value: "warehouse", label: "A cloud data warehouse" },
                  { value: "data_lake", label: "A data lake" },
                  { value: "both", label: "Both a lake and a warehouse" },
                  { value: "lakehouse", label: "Already a lakehouse" },
                  { value: "databases_only", label: "Operational databases only" },
                  { value: "none", label: "Nothing formal yet" },
                ]}
              />
              <ChipMultiSelect
                label="What are your biggest infrastructure challenges?"
                values={answers.challenges}
                onChange={(values) => set("challenges", values)}
                options={[
                  { value: "cost", label: "Cost" },
                  { value: "data_residency", label: "Data residency" },
                  { value: "vendor_lock_in", label: "Vendor lock-in" },
                  { value: "performance", label: "Performance" },
                  { value: "slow_queries", label: "Slow queries" },
                  { value: "governance", label: "Governance" },
                  { value: "compliance", label: "Compliance" },
                  { value: "data_silos", label: "Data silos" },
                  { value: "duplicate_copies", label: "Duplicate copies of data" },
                  { value: "scaling", label: "Scaling" },
                ]}
              />
            </>
          )}

          {step.id === "operations" && (
            <>
              <RadioCardGroup
                name="kubernetes_maturity"
                label="How much Kubernetes experience do you have?"
                description="IOMETE is Kubernetes-native. Answering honestly here is what makes the rest of the assessment worth anything."
                required
                value={answers.kubernetes_maturity as string}
                onChange={(value) => set("kubernetes_maturity", value)}
                error={
                  touched && missing.includes("kubernetes_maturity")
                    ? "Pick one to continue."
                    : null
                }
                options={[
                  {
                    value: "production",
                    label: "We run Kubernetes in production",
                    hint: "The strongest readiness signal there is",
                  },
                  { value: "advanced", label: "Advanced — multiple clusters, confident" },
                  { value: "some", label: "Some experience, not in production" },
                  { value: "basic", label: "Basic — we have looked at it" },
                  {
                    value: "none",
                    label: "None",
                    hint: "This caps the assessment at conditional, and we will say why",
                  },
                ]}
              />
              <Select
                label="How big is the team that would operate this?"
                placeholder="Choose one"
                value={answers.team_size ?? ""}
                onChange={(event) => set("team_size", event.target.value)}
                options={[
                  { value: "dedicated platform team", label: "A dedicated platform team" },
                  { value: "large", label: "Large — more than five people" },
                  { value: "medium", label: "Medium — three to five people" },
                  { value: "small", label: "Small — one or two people" },
                ]}
              />
              <ChipMultiSelect
                label="What operational constraints apply?"
                values={answers.constraints}
                onChange={(values) => set("constraints", values)}
                options={[
                  { value: "tight_timeline", label: "Tight timeline" },
                  { value: "limited_budget", label: "Limited budget" },
                  { value: "small_team", label: "Small team" },
                  { value: "procurement_process", label: "Long procurement process" },
                  { value: "change_freeze", label: "Change freeze windows" },
                ]}
              />
            </>
          )}

          {step.id === "contact" && (
            <>
              <Card tone="sunken">
                <Eyebrow as="h3">You can stop here</Eyebrow>
                <p className="mt-2 text-small text-ink-muted">
                  Your assessment and architecture recommendation will be generated either
                  way, and you will get a link you can return to. Contact details are only
                  needed if you want the IOMETE team to follow up.
                </p>
              </Card>

              <div className="grid gap-4 sm:grid-cols-2">
                <Input
                  label="Your name"
                  hint="Optional"
                  autoComplete="name"
                  value={contact.name}
                  onChange={(event) =>
                    setContact((current) => ({ ...current, name: event.target.value }))
                  }
                />
                <Input
                  label="Work email"
                  type="email"
                  hint="Optional"
                  autoComplete="email"
                  value={contact.email}
                  onChange={(event) =>
                    setContact((current) => ({ ...current, email: event.target.value }))
                  }
                  error={submit.fieldErrors.contact_email}
                />
              </div>

              {(contact.email || contact.name) && (
                <Checkbox
                  label="I agree to be contacted about this enquiry"
                  description={CONSENT_TEXT}
                  checked={consent}
                  onChange={(event) => setConsent(event.target.checked)}
                  error={
                    touched && needsConsent
                      ? "Tick this, or remove your contact details — the assessment works anonymously."
                      : null
                  }
                />
              )}
            </>
          )}
        </div>

        <FormError error={submit.error} className="mt-6" />

        <div className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-5">
          <Button
            variant="ghost"
            onClick={retreat}
            disabled={stepIndex === 0 || submit.pending}
            icon={<ArrowLeft />}
          >
            Back
          </Button>

          <Button
            variant="primary"
            size="lg"
            onClick={() => {
              if (isLast && needsConsent) {
                setTouched(true);
                return;
              }
              advance();
            }}
            loading={submit.pending}
            iconRight={isLast ? <Sparkles /> : <ArrowRight />}
          >
            {isLast ? "Generate my assessment" : "Continue"}
          </Button>
        </div>

        {touched && missing.length > 0 && (
          <p role="alert" className="mt-3 text-right text-small text-critical">
            Answer the required question above to continue.
          </p>
        )}
      </Card>
    </div>
  );
}
