"use client";

import * as React from "react";

import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleDot,
  Eye,
  FlaskConical,
  Lock,
  ShieldAlert,
  ShieldCheck,
  Siren,
  Wrench,
} from "lucide-react";

import { api } from "@/lib/api";
import { useMutation } from "@/lib/hooks";
import type { Execution, PlaybookStep, StepResponse } from "@/lib/types";
import { cn, duration, formatDateTime } from "@/lib/utils";

import {
  Badge,
  Button,
  Card,
  CodeBlock,
  Divider,
  Eyebrow,
  FormError,
  RadioCardGroup,
  Textarea,
  useToast,
} from "@/components/ui";

/**
 * Step types, and how seriously each must be presented.
 *
 * `read_only_diagnostic` and `verification` observe. `configuration_change`,
 * `change_requiring_approval` and `remediation` alter a running system. The visual
 * weight is not decoration: a reader skimming the page has to be able to tell, before
 * they act, whether the step they are about to run changes anything.
 */
const STEP_PRESENTATION: Record<
  string,
  { icon: React.ReactNode; tone: "neutral" | "info" | "caution" | "critical"; border: string }
> = {
  read_only_diagnostic: { icon: <Eye />, tone: "neutral", border: "border-border" },
  verification: { icon: <ShieldCheck />, tone: "info", border: "border-info/30" },
  configuration_change: { icon: <Wrench />, tone: "caution", border: "border-caution/40" },
  change_requiring_approval: {
    icon: <ShieldAlert />,
    tone: "critical",
    border: "border-critical/40",
  },
  remediation: { icon: <Siren />, tone: "critical", border: "border-critical/40" },
  escalation: { icon: <AlertTriangle />, tone: "critical", border: "border-critical/40" },
};

const RISK_TONE: Record<string, "neutral" | "caution" | "critical"> = {
  low: "neutral",
  medium: "caution",
  high: "critical",
};

const OUTCOMES = [
  {
    value: "resolved",
    label: "Resolved",
    hint: "The problem is gone and I have verified it.",
  },
  {
    value: "partially_resolved",
    label: "Partially resolved",
    hint: "Better, but not fully fixed.",
  },
  { value: "not_resolved", label: "Not resolved", hint: "The problem persists." },
  {
    value: "escalated",
    label: "I need an engineer",
    hint: "Hand this to IOMETE with everything recorded so far.",
  },
] as const;

/**
 * Resolution Replay.
 *
 * The product's differentiator, and the one screen where getting the safety model wrong
 * would matter most. Three rules are enforced here and restated on screen:
 *
 *  1. **Nothing is executed.** Every command is displayed for the reader to run
 *     themselves. There is no code path in this component that runs anything, and the
 *     notice saying so is not dismissible.
 *  2. **A system-changing step cannot be completed without an authorised approval.** The
 *     backend enforces it; this refuses to submit without it so the person is told why
 *     rather than receiving a 403.
 *  3. **Every answer is recorded.** The trail below the live step is the investigation
 *     history — it is what makes an escalation useful and what the knowledge extractor
 *     later reads.
 */
export function ReplayRunner({
  execution: initial,
  onFinished,
}: {
  execution: Execution;
  onFinished?: (execution: Execution) => void;
}) {
  const [execution, setExecution] = React.useState(initial);
  const [response, setResponse] = React.useState("");
  const [observation, setObservation] = React.useState("");
  const [approvalNote, setApprovalNote] = React.useState("");
  const [touched, setTouched] = React.useState(false);
  const [outcomePrompt, setOutcomePrompt] = React.useState<string | null>(null);
  const [outcome, setOutcome] = React.useState("");
  const [outcomeSummary, setOutcomeSummary] = React.useState("");

  const toast = useToast();
  const stepHeadingRef = React.useRef<HTMLHeadingElement>(null);

  const step = execution.current_step_detail;
  const finished = execution.status !== "in_progress";

  const advance = useMutation(
    async () =>
      api.advanceExecution(execution.id, {
        response_value: response,
        ...(observation ? { observation } : {}),
        ...(approvalNote ? { approval_note: approvalNote } : {}),
      }),
    {
      onSuccess: (result) => {
        setExecution(result.execution);
        setResponse("");
        setObservation("");
        setApprovalNote("");
        setTouched(false);
        if (result.requires_outcome_capture) {
          setOutcomePrompt(result.outcome_prompt || "How did this end?");
        }
        // Focus the new step so a keyboard user is moved forward with the content.
        requestAnimationFrame(() => stepHeadingRef.current?.focus());
      },
    },
  );

  const complete = useMutation(
    async () =>
      api.completeExecution(execution.id, {
        outcome,
        ...(outcomeSummary ? { outcome_summary: outcomeSummary } : {}),
      }),
    {
      onSuccess: (result) => {
        setExecution(result);
        setOutcomePrompt(null);
        toast.success(
          "Replay closed",
          "Your answers are recorded against the ticket.",
        );
        onFinished?.(result);
      },
    },
  );

  const needsApproval = Boolean(step?.requires_approval);
  const canApprove = step?.can_current_user_approve !== false;
  const approvalBlocked = needsApproval && !canApprove;
  const approvalMissing = needsApproval && canApprove && approvalNote.trim().length === 0;

  const onSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (!response.trim() || approvalMissing || approvalBlocked) return;
    void advance.run();
  };

  const progress = execution.total_steps
    ? execution.steps_completed / execution.total_steps
    : 0;

  return (
    <div className="space-y-5">
      {/* ------------------------------------------------------------- Header */}
      <Card tone="raised">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <Eyebrow as="h2">Resolution Replay</Eyebrow>
            <h3 className="mt-1.5 text-h2 text-ink">{execution.playbook_title}</h3>
            <p className="mt-1.5 text-small text-ink-subtle">
              Verified playbook v{execution.playbook_version} · started by{" "}
              {execution.started_by_name ?? "you"} ·{" "}
              {formatDateTime(execution.created_at)}
            </p>
          </div>
          <Badge tone={finished ? "positive" : "accent"}>{execution.status_label}</Badge>
        </div>

        <div className="mt-5">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-small text-ink-muted">
              Step {Math.min(execution.steps_completed + (finished ? 0 : 1), execution.total_steps)}{" "}
              of {execution.total_steps}
            </span>
            <span className="text-small tabular text-ink-subtle">
              {execution.steps_completed} completed
              {execution.duration_seconds !== null &&
                ` · ${duration(execution.duration_seconds)}`}
            </span>
          </div>
          <div
            role="progressbar"
            aria-valuenow={execution.steps_completed}
            aria-valuemin={0}
            aria-valuemax={execution.total_steps}
            aria-label="Replay progress"
            className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-inset"
          >
            <div
              className="h-full rounded-full bg-accent-500 transition-[width] duration-500"
              style={{ width: `${Math.max(progress > 0 ? 3 : 0, progress * 100)}%` }}
            />
          </div>
        </div>

        {/* Non-dismissible. The whole safety model rests on this being true and said. */}
        <div className="mt-5 flex items-start gap-2.5 rounded-md border border-border bg-surface-sunken px-3.5 py-3">
          <Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-ink-subtle" />
          <p className="text-small text-ink-muted">
            <span className="font-medium text-ink">COMPASS runs nothing.</span> Every
            command below is shown for you to run yourself, against your own cluster, and
            the result is whatever you tell us it was. Nothing on this page reaches your
            infrastructure.
          </p>
        </div>
      </Card>

      {/* --------------------------------------------------------- Live step */}
      {!finished && step && !outcomePrompt && (
        <StepCard
          step={step}
          headingRef={stepHeadingRef}
          sequence={execution.steps_completed + 1}
        >
          <form onSubmit={onSubmit} className="space-y-5">
            {step.response_kind === "choice" && step.response_options.length > 0 ? (
              <RadioCardGroup
                name={`step-${step.key}`}
                label="What did you observe?"
                required
                value={response}
                onChange={setResponse}
                error={touched && !response ? "Record what you saw to continue." : null}
                options={step.response_options.map((option) => ({
                  value: option.value,
                  label: option.label,
                  ...(option.hint ? { hint: option.hint } : {}),
                }))}
              />
            ) : (
              <Textarea
                label="What did you observe?"
                required
                rows={3}
                value={response}
                onChange={(event) => setResponse(event.target.value)}
                placeholder={step.expected_observation || "Paste or describe the output"}
                error={touched && !response ? "Record what you saw to continue." : null}
              />
            )}

            <Textarea
              label="Notes"
              hint="Optional — anything that does not fit the answer above"
              rows={2}
              value={observation}
              onChange={(event) => setObservation(event.target.value)}
            />

            {needsApproval && (
              <ApprovalGate
                canApprove={canApprove}
                note={approvalNote}
                onNoteChange={setApprovalNote}
                error={
                  touched && approvalMissing
                    ? "State who authorised this change before recording it as done."
                    : null
                }
              />
            )}

            <FormError error={advance.error} />

            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="submit"
                variant="primary"
                loading={advance.pending}
                disabled={approvalBlocked}
                iconRight={<ArrowRight />}
              >
                Record and continue
              </Button>
              {approvalBlocked && (
                <span className="text-small text-critical">
                  Your role cannot approve a system-changing step.
                </span>
              )}
            </div>
          </form>
        </StepCard>
      )}

      {/* ----------------------------------------------------- Outcome capture */}
      {outcomePrompt && !finished && (
        <Card className="border-accent-300">
          <Eyebrow as="h3">One last thing</Eyebrow>
          <h4 className="mt-1.5 text-h3 text-ink">{outcomePrompt}</h4>
          <p className="mt-2 text-small text-ink-muted measure">
            This is the answer that turns your investigation into reusable knowledge. An
            honest &ldquo;not resolved&rdquo; is more useful to the next person than an
            optimistic one.
          </p>

          <div className="mt-5 space-y-5">
            <RadioCardGroup
              name="outcome"
              label="How did it end?"
              required
              columns={2}
              value={outcome}
              onChange={setOutcome}
              options={OUTCOMES.map((option) => ({ ...option }))}
            />
            <Textarea
              label="In a sentence, what happened?"
              hint="Optional, but it is what the next person reads first"
              rows={3}
              value={outcomeSummary}
              onChange={(event) => setOutcomeSummary(event.target.value)}
            />
            <FormError error={complete.error} />
            <Button
              variant="primary"
              onClick={() => void complete.run()}
              loading={complete.pending}
              disabled={!outcome}
              icon={<CheckCircle2 />}
            >
              Close the replay
            </Button>
          </div>
        </Card>
      )}

      {/* ------------------------------------------------------------ Finished */}
      {finished && <Outcome execution={execution} />}

      {/* -------------------------------------------------------------- Trail */}
      {execution.responses.length > 0 && (
        <Card tone="flat">
          <Eyebrow as="h3">What you have recorded</Eyebrow>
          <p className="mt-1.5 text-small text-ink-muted">
            The investigation trail. If this is escalated, an engineer starts from here
            instead of asking you the same questions again.
          </p>
          <ol className="mt-4 space-y-3">
            {[...execution.responses]
              .sort((a, b) => b.sequence - a.sequence)
              .map((entry) => (
                <TrailEntry key={entry.id} entry={entry} />
              ))}
          </ol>
        </Card>
      )}
    </div>
  );
}

// =====================================================================================
// Pieces
// =====================================================================================

function StepCard({
  step,
  sequence,
  headingRef,
  children,
}: {
  step: PlaybookStep;
  sequence: number;
  headingRef: React.RefObject<HTMLHeadingElement | null>;
  children: React.ReactNode;
}) {
  const presentation =
    STEP_PRESENTATION[step.step_type] ?? STEP_PRESENTATION.read_only_diagnostic!;

  return (
    <Card className={cn("border", presentation.border)}>
      <div className="flex flex-wrap items-start gap-3">
        <span
          aria-hidden="true"
          className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-md bg-surface-sunken text-ink-muted [&>svg]:size-[18px]"
        >
          {presentation.icon}
        </span>
        <div className="min-w-0 flex-1">
          <Eyebrow>Step {sequence}</Eyebrow>
          <h3
            ref={headingRef}
            tabIndex={-1}
            className="mt-1 text-h3 text-ink focus-visible:outline-none"
          >
            {step.title}
          </h3>
          <div className="mt-2.5 flex flex-wrap gap-2">
            <Badge tone={presentation.tone} size="sm">
              {step.step_type_label}
            </Badge>
            <Badge tone={RISK_TONE[step.risk_level] ?? "neutral"} size="sm">
              {step.risk_level_label}
            </Badge>
            {step.is_read_only ? (
              <Badge tone="positive" size="sm">
                Changes nothing
              </Badge>
            ) : (
              <Badge tone="critical" size="sm">
                Changes your system
              </Badge>
            )}
          </div>
        </div>
      </div>

      <div className="mt-5 space-y-4">
        <p className="text-body leading-relaxed text-ink-muted measure">
          {step.plain_explanation}
        </p>

        {step.why_this_step && (
          <div className="rounded-md bg-surface-sunken px-3.5 py-3">
            <p className="text-small text-ink-muted">
              <span className="font-medium text-ink">Why this step: </span>
              {step.why_this_step}
            </p>
          </div>
        )}

        {!step.is_read_only && step.blast_radius && (
          <div className="flex items-start gap-2.5 rounded-md border border-critical/30 bg-critical-soft px-3.5 py-3">
            <AlertTriangle
              aria-hidden="true"
              className="mt-0.5 size-4 shrink-0 text-critical"
            />
            <p className="text-small text-ink-muted">
              <span className="font-medium text-ink">What this affects: </span>
              {step.blast_radius}
            </p>
          </div>
        )}

        {step.what_to_inspect && (
          <div>
            <Eyebrow as="h4">What to look at</Eyebrow>
            <p className="mt-1.5 text-small text-ink-muted measure">
              {step.what_to_inspect}
            </p>
          </div>
        )}

        {step.commands.length > 0 && (
          <div className="space-y-2.5">
            <Eyebrow as="h4">Run this yourself</Eyebrow>
            {step.commands.map((command) => (
              <CodeBlock
                key={command.command}
                label={command.label}
                caution={
                  command.is_read_only === false
                    ? "This command changes your system. Read it before you run it."
                    : undefined
                }
              >
                {command.command}
              </CodeBlock>
            ))}
            <p className="text-[11px] leading-snug text-ink-subtle">
              {step.commands_notice}
            </p>
          </div>
        )}

        {step.expected_observation && (
          <div className="rounded-md border border-info/25 bg-info-soft px-3.5 py-3">
            <p className="text-small text-ink-muted">
              <span className="font-medium text-ink">Expected: </span>
              {step.expected_observation}
            </p>
          </div>
        )}

        {step.references.length > 0 && (
          <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
            {step.references.map((reference) => (
              <li key={reference.url}>
                <a
                  href={reference.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-small text-accent-700 underline decoration-accent-300 underline-offset-2 dark:text-accent-400"
                >
                  {reference.title}
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>

      <Divider className="my-6" />
      {children}
    </Card>
  );
}

/**
 * The approval gate.
 *
 * A step that changes a running system cannot be recorded as done without naming who
 * authorised it. The backend is the enforcement point; this exists so the person is told
 * what is required *before* they are refused, and so the record of who approved what is
 * captured at the moment it happens rather than reconstructed later.
 */
function ApprovalGate({
  canApprove,
  note,
  onNoteChange,
  error,
}: {
  canApprove: boolean;
  note: string;
  onNoteChange: (value: string) => void;
  error: string | null;
}) {
  return (
    <div className="rounded-lg border border-critical/40 bg-critical-soft p-4">
      <div className="flex items-start gap-2.5">
        <ShieldAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-critical" />
        <div className="min-w-0 flex-1">
          <h4 className="text-small font-medium text-ink">
            This step needs authorisation
          </h4>
          <p className="mt-1 text-small text-ink-muted">
            It changes a running system. COMPASS records who approved it, and will not
            mark it complete without that record.
          </p>

          {canApprove ? (
            <div className="mt-3.5">
              <Textarea
                label="Who authorised this, and on what basis?"
                required
                rows={2}
                value={note}
                onChange={(event) => onNoteChange(event.target.value)}
                placeholder="e.g. Approved by the platform lead in change CHG-4821, in the Tuesday maintenance window."
                error={error}
              />
            </div>
          ) : (
            <p className="mt-3 flex items-start gap-2 text-small text-critical">
              <Lock aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
              Your role cannot authorise this. Ask an administrator in your organisation,
              or escalate to IOMETE — everything recorded so far travels with it.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function Outcome({ execution }: { execution: Execution }) {
  const resolved = execution.status === "resolved";
  const escalated = execution.status === "escalated";

  return (
    <Card
      className={cn(
        "border",
        resolved ? "border-positive/40 bg-positive-soft" : "border-caution/40 bg-caution-soft",
      )}
    >
      <div className="flex flex-wrap items-start gap-4">
        <span
          aria-hidden="true"
          className="grid size-10 shrink-0 place-items-center rounded-full bg-surface-raised [&>svg]:size-5"
        >
          {resolved ? (
            <CheckCircle2 className="text-positive" />
          ) : (
            <AlertTriangle className="text-caution" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <Eyebrow as="h3">Replay closed</Eyebrow>
          <h4 className="mt-1.5 text-h2 text-ink">{execution.status_label}</h4>
          {execution.outcome_summary && (
            <p className="mt-2.5 text-body text-ink-muted measure">
              {execution.outcome_summary}
            </p>
          )}
          <p className="mt-3 text-small text-ink-subtle">
            {execution.steps_completed} of {execution.total_steps} steps recorded
            {execution.duration_seconds !== null &&
              ` over ${duration(execution.duration_seconds)}`}
            .
            {escalated &&
              " Your trail has gone to IOMETE — an engineer starts from what you found, not from scratch."}
            {resolved &&
              " This outcome feeds the knowledge base, so the next organisation with this problem reaches the answer faster."}
          </p>
        </div>
      </div>
    </Card>
  );
}

function TrailEntry({ entry }: { entry: StepResponse }) {
  const matched = entry.matched_expectation;
  return (
    <li className="rounded-md border border-border bg-surface-raised p-3.5">
      <div className="flex flex-wrap items-start justify-between gap-2.5">
        <span className="inline-flex items-center gap-2 text-small font-medium text-ink">
          <CircleDot aria-hidden="true" className="size-3.5 shrink-0 text-ink-subtle" />
          {entry.step_title}
        </span>
        <span className="text-[11px] text-ink-subtle">
          {formatDateTime(entry.created_at)}
        </span>
      </div>

      <dl className="mt-2.5 space-y-1.5">
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-small text-ink-subtle">You recorded:</dt>
          <dd className="text-small text-ink">{entry.response_value || "—"}</dd>
        </div>
        {entry.observation && (
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-small text-ink-subtle">Notes:</dt>
            <dd className="text-small text-ink-muted">{entry.observation}</dd>
          </div>
        )}
        {entry.approval_granted_by_name && (
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-small text-ink-subtle">Approved by:</dt>
            <dd className="text-small text-ink">
              {entry.approval_granted_by_name}
              {entry.approval_note && (
                <span className="text-ink-muted"> — {entry.approval_note}</span>
              )}
            </dd>
          </div>
        )}
      </dl>

      {matched !== null && (
        <p className="mt-2.5">
          <Badge tone={matched ? "positive" : "caution"} size="sm">
            {matched ? "Matched what the playbook expected" : "Differed from expected"}
          </Badge>
        </p>
      )}
    </li>
  );
}

/** Shown before a replay starts, so the reader knows what they are agreeing to. */
export function ReplayIntro({ stepCount }: { stepCount: number }) {
  return (
    <Card tone="sunken">
      <div className="flex items-start gap-2.5">
        <FlaskConical
          aria-hidden="true"
          className="mt-0.5 size-4 shrink-0 text-accent-700 dark:text-accent-400"
        />
        <div>
          <h3 className="text-small font-medium text-ink">
            What a replay is
          </h3>
          <p className="mt-1 text-small text-ink-muted measure">
            {stepCount} steps that an IOMETE engineer already used to resolve this problem
            for someone else, reviewed and approved before being offered to you. You run
            each command yourself and tell COMPASS what you saw; it decides what to ask
            next. Nothing is executed on your behalf, and you can stop at any point and
            hand the whole trail to an engineer.
          </p>
        </div>
      </div>
    </Card>
  );
}
