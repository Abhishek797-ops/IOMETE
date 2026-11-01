"use client";

import * as React from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { ArrowRight, CalendarCheck, CheckCircle2, FileText, Send } from "lucide-react";

import { api } from "@/lib/api";
import { useMutation, useResource } from "@/lib/hooks";
import type { DemoRequest, FitAssessment } from "@/lib/types";

import {
  Badge,
  Button,
  Card,
  Checkbox,
  ChipMultiSelect,
  Eyebrow,
  FormError,
  Input,
  Select,
  SkeletonText,
  Textarea,
} from "@/components/ui";

const CONSENT_TEXT =
  "I agree that IOMETE may contact me about this request using the details above. " +
  "My answers and, if attached, my fit assessment will be shared with the IOMETE team.";

const INTERESTS = [
  { value: "architecture", label: "Architecture review" },
  { value: "deployment", label: "Deployment and Kubernetes" },
  { value: "governance", label: "Governance and access control" },
  { value: "migration", label: "Migrating off a warehouse" },
  { value: "sovereignty", label: "Data sovereignty and residency" },
  { value: "cost", label: "Cost model" },
  { value: "integrations", label: "Integrations with our stack" },
  { value: "support", label: "Support and forward-deployed engineering" },
] as const;

const TIMEFRAMES = [
  { value: "this_week", label: "This week" },
  { value: "next_two_weeks", label: "In the next two weeks" },
  { value: "this_month", label: "Within the month" },
  { value: "this_quarter", label: "This quarter" },
  { value: "exploring", label: "No timeline — still exploring" },
];

/**
 * The demo request.
 *
 * Attaching a completed fit assessment is what makes this a qualified conversation rather
 * than a form fill: the engineer arrives already knowing the prospect's infrastructure,
 * constraints and open questions. When `?assessment=<id>` is present the form fetches it,
 * shows exactly what will be shared, and says plainly that it can be detached.
 */
export function DemoRequestForm() {
  return (
    <React.Suspense fallback={<SkeletonText lines={6} />}>
      <DemoRequestInner />
    </React.Suspense>
  );
}

function DemoRequestInner() {
  const params = useSearchParams();
  const assessmentId = params.get("assessment");

  const [attach, setAttach] = React.useState(true);
  const [fields, setFields] = React.useState({
    contact_name: "",
    contact_email: "",
    company_name: "",
    contact_role: "",
    message: "",
    preferred_timeframe: "",
  });
  const [interests, setInterests] = React.useState<string[]>([]);
  const [consent, setConsent] = React.useState(false);
  const [touched, setTouched] = React.useState(false);
  const [confirmed, setConfirmed] = React.useState<
    (DemoRequest & { confirmation?: string }) | null
  >(null);

  const assessment = useResource<FitAssessment>(
    async () => api.fitAssessment(assessmentId!),
    [assessmentId],
    { enabled: Boolean(assessmentId) },
  );

  const submit = useMutation(
    async () =>
      api.createDemoRequest({
        ...fields,
        interests,
        consent_given: consent,
        ...(assessmentId && attach ? { assessment: assessmentId } : {}),
      }) as Promise<DemoRequest & { confirmation?: string }>,
    { onSuccess: setConfirmed },
  );

  const required: (keyof typeof fields)[] = ["contact_name", "contact_email", "company_name"];
  const missing = required.filter((field) => !fields[field].trim());

  const onSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (missing.length > 0 || !consent) return;
    void submit.run();
  };

  const set = (key: keyof typeof fields) => (
    event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>,
  ) => setFields((current) => ({ ...current, [key]: event.target.value }));

  if (confirmed) {
    return <Confirmation request={confirmed} />;
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_20rem] lg:gap-10">
      <Card>
        <form onSubmit={onSubmit} noValidate className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <Input
              label="Your name"
              required
              autoComplete="name"
              value={fields.contact_name}
              onChange={set("contact_name")}
              error={
                (touched && missing.includes("contact_name") ? "Tell us who you are." : null) ??
                submit.fieldErrors.contact_name
              }
            />
            <Input
              label="Work email"
              type="email"
              required
              autoComplete="email"
              value={fields.contact_email}
              onChange={set("contact_email")}
              error={
                (touched && missing.includes("contact_email")
                  ? "We need an address to reply to."
                  : null) ?? submit.fieldErrors.contact_email
              }
            />
            <Input
              label="Organisation"
              required
              autoComplete="organization"
              value={fields.company_name}
              onChange={set("company_name")}
              error={
                (touched && missing.includes("company_name")
                  ? "Which organisation is this for?"
                  : null) ?? submit.fieldErrors.company_name
              }
            />
            <Input
              label="Your role"
              hint="Optional"
              autoComplete="organization-title"
              value={fields.contact_role}
              onChange={set("contact_role")}
              error={submit.fieldErrors.contact_role}
            />
          </div>

          <Select
            label="When would you like to speak?"
            description="Indicative only — nothing is booked by this form."
            placeholder="No preference"
            options={TIMEFRAMES}
            value={fields.preferred_timeframe}
            onChange={set("preferred_timeframe")}
          />

          <ChipMultiSelect
            label="What should the conversation cover?"
            description="Pick as many as apply. This routes the request to the right engineer."
            options={INTERESTS.map((interest) => ({ ...interest }))}
            values={interests}
            onChange={setInterests}
          />

          <Textarea
            label="Anything else worth knowing?"
            hint="Optional"
            rows={4}
            placeholder="Constraints, deadlines, the specific question you need answered…"
            value={fields.message}
            onChange={set("message")}
            error={submit.fieldErrors.message}
          />

          <div className="border-t border-border pt-5">
            <Checkbox
              label="I agree to be contacted about this request"
              description={CONSENT_TEXT}
              checked={consent}
              onChange={(event) => setConsent(event.target.checked)}
              error={
                touched && !consent
                  ? "We cannot pass this to the team without your agreement."
                  : (submit.fieldErrors.consent_given ?? null)
              }
            />
          </div>

          <FormError error={submit.error} />

          <Button
            type="submit"
            variant="primary"
            size="lg"
            loading={submit.pending}
            icon={<Send />}
          >
            Send the request
          </Button>

          <p className="text-[11px] leading-snug text-ink-subtle">
            COMPASS stores only what is on this form. Nothing is sent anywhere else, and no
            meeting is scheduled automatically — a person reads this and replies.
          </p>
        </form>
      </Card>

      {/* --------------------------------------------------- Attached context */}
      <aside className="min-w-0 space-y-5 lg:sticky lg:top-24 lg:self-start">
        {assessmentId ? (
          <Card tone="raised">
            <div className="flex items-start gap-2.5">
              <FileText
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 text-accent-700 dark:text-accent-400"
              />
              <div className="min-w-0">
                <Eyebrow as="h3">Attached assessment</Eyebrow>
                {assessment.loading && <SkeletonText lines={3} className="mt-2" />}
                {assessment.error && (
                  <p className="mt-2 text-small text-ink-muted">
                    That assessment could not be loaded, so nothing will be attached. The
                    request will still reach the team.
                  </p>
                )}
                {assessment.data && (
                  <>
                    <p className="mt-1.5 flex flex-wrap items-center gap-2">
                      <Badge tone="accent" size="sm">
                        {assessment.data.band_label}
                      </Badge>
                      <span className="text-small tabular text-ink-subtle">
                        {assessment.data.indicative_score}/100 indicative
                      </span>
                    </p>
                    <p className="mt-2.5 text-small text-ink-muted">
                      Attaching it means the engineer arrives knowing your infrastructure,
                      your {assessment.data.gaps.length} identified gaps and the{" "}
                      {assessment.data.questions_for_sales.length} questions COMPASS could
                      not answer from public documentation.
                    </p>
                    <div className="mt-3.5 border-t border-border pt-3.5">
                      <Checkbox
                        label="Attach my fit assessment"
                        checked={attach}
                        onChange={(event) => setAttach(event.target.checked)}
                      />
                    </div>
                    <Link
                      href={`/fit-finder?assessment=${assessmentId}`}
                      className="mt-3 inline-flex items-center gap-1 text-small font-medium text-accent-700 underline decoration-accent-300 underline-offset-2 dark:text-accent-400"
                    >
                      Review it first
                      <ArrowRight aria-hidden="true" className="size-3.5" />
                    </Link>
                  </>
                )}
              </div>
            </div>
          </Card>
        ) : (
          <Card tone="sunken">
            <Eyebrow as="h3">Make this a better conversation</Eyebrow>
            <p className="mt-2 text-small text-ink-muted">
              Running the Fit Finder first takes about four minutes and attaches your
              infrastructure, constraints and open questions to this request — so the first
              call starts with specifics instead of discovery.
            </p>
            <Link href="/fit-finder" className="mt-3.5 block">
              <Button variant="secondary" fullWidth iconRight={<ArrowRight />}>
                Run the Fit Finder
              </Button>
            </Link>
          </Card>
        )}

        <Card tone="flat">
          <Eyebrow as="h3">What happens next</Eyebrow>
          <ol className="mt-3 space-y-2.5">
            {[
              "An IOMETE engineer reads the request, with your assessment if you attached it.",
              "They reply by email to arrange a time. Nothing is booked by this form.",
              "The conversation starts from your environment, not from a slide deck.",
            ].map((step, index) => (
              <li key={step} className="flex items-start gap-2.5">
                <span
                  aria-hidden="true"
                  className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-surface-inset text-[11px] font-semibold text-ink-muted"
                >
                  {index + 1}
                </span>
                <span className="text-small text-ink-muted">{step}</span>
              </li>
            ))}
          </ol>
        </Card>
      </aside>
    </div>
  );
}

function Confirmation({ request }: { request: DemoRequest & { confirmation?: string } }) {
  const headingRef = React.useRef<HTMLHeadingElement>(null);
  React.useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <Card className="border-positive/40 bg-positive-soft">
      <div className="flex flex-wrap items-start gap-5">
        <span
          aria-hidden="true"
          className="grid size-11 shrink-0 place-items-center rounded-full bg-surface-raised text-positive [&>svg]:size-5"
        >
          <CheckCircle2 />
        </span>
        <div className="min-w-[16rem] flex-1">
          <Eyebrow>Request received</Eyebrow>
          <h2
            ref={headingRef}
            tabIndex={-1}
            className="mt-1.5 text-h1 text-ink focus-visible:outline-none"
          >
            That is with the team
          </h2>
          <p className="mt-3 text-body leading-relaxed text-ink-muted measure">
            {request.confirmation ??
              "Thank you — your request has been recorded and a person will read it."}
          </p>

          <dl className="mt-5 grid gap-x-6 gap-y-2 sm:grid-cols-2">
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-ink-subtle">
                Reference
              </dt>
              <dd className="mt-0.5 font-mono text-small text-ink">
                {request.id.slice(0, 8)}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-ink-subtle">Status</dt>
              <dd className="mt-0.5 text-small text-ink">{request.status_label}</dd>
            </div>
          </dl>

          <div className="mt-6 flex flex-wrap gap-2.5">
            <Link href="/lakehouse-playground">
              <Button variant="secondary" icon={<CalendarCheck />}>
                Explore while you wait
              </Button>
            </Link>
            <Link href="/explore">
              <Button variant="ghost" iconRight={<ArrowRight />}>
                Read the explainer
              </Button>
            </Link>
          </div>
        </div>
      </div>
    </Card>
  );
}
