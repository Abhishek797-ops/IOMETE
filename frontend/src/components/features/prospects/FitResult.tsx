"use client";

import * as React from "react";

import Link from "next/link";

import {
  AlertTriangle,
  ArrowRight,
  CalendarCheck,
  CheckCircle2,
  Download,
  HelpCircle,
  Lightbulb,
  Link2,
  RotateCcw,
  Scale,
  ShieldAlert,
  Wrench,
} from "lucide-react";

import type {
  ArchitectureRecommendation,
  FitAssessment,
  FitAssessmentResponse,
  FitBand,
  FitGap,
  GraphLegendEntry,
  RubricEntry,
} from "@/lib/types";
import { cn, downloadFile, percent } from "@/lib/utils";

import { ArchitectureCanvas } from "@/components/diagrams/ArchitectureCanvas";
import {
  Badge,
  Button,
  Card,
  ClaimStatusBadge,
  Disclaimer,
  Disclosure,
  Divider,
  Eyebrow,
  NodeClaimBadge,
  ProgressBar,
  SourceIds,
  SourceList,
  Tabs,
  useToast,
} from "@/components/ui";

const BAND_PRESENTATION: Record<
  FitBand,
  {
    tone: "positive" | "accent" | "caution" | "critical" | "info";
    ring: string;
    icon: React.ReactNode;
  }
> = {
  strong: {
    tone: "positive",
    ring: "border-positive/40 bg-positive-soft",
    icon: <CheckCircle2 />,
  },
  promising: {
    tone: "accent",
    ring: "border-accent-300 bg-accent-50",
    icon: <Lightbulb />,
  },
  conditional: {
    tone: "caution",
    ring: "border-caution/40 bg-caution-soft",
    icon: <Scale />,
  },
  limited: {
    tone: "critical",
    ring: "border-critical/40 bg-critical-soft",
    icon: <ShieldAlert />,
  },
  needs_discussion: {
    tone: "info",
    ring: "border-info/40 bg-info-soft",
    icon: <HelpCircle />,
  },
};

const SEVERITY_TONE: Record<FitGap["severity"], "critical" | "caution" | "neutral"> = {
  high: "critical",
  medium: "caution",
  low: "neutral",
};

/**
 * The Fit Finder result.
 *
 * Ordered by what a reader most needs and least wants to hear: the band and its honest
 * explanation, then the score with its caveat attached rather than footnoted, then the
 * rubric that produced it, then what IOMETE would require of them, then the gaps.
 *
 * The score is never the hero. It is a weighted sum of a published rubric, shown beside
 * that rubric, with the server's caveat text directly under the number — the prohibition
 * on misleading compatibility percentages is a presentation requirement as much as a
 * scoring one.
 */
export function FitResult({
  result,
  onRestart,
}: {
  result: FitAssessmentResponse;
  onRestart: () => void;
}) {
  const { assessment, architecture, caps_applied, legend, rubric_definition_url } = result;
  const band = BAND_PRESENTATION[assessment.band] ?? BAND_PRESENTATION.needs_discussion;
  const toast = useToast();

  const headingRef = React.useRef<HTMLHeadingElement>(null);
  React.useEffect(() => {
    // The wizard has just been replaced by this result. Without moving focus, a keyboard
    // user is left on a button that no longer exists and a screen reader announces nothing.
    headingRef.current?.focus();
  }, []);

  const copyLink = async () => {
    const url = `${window.location.origin}/fit-finder?assessment=${assessment.id}`;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Link copied", url);
    } catch {
      toast.error(
        "Could not copy",
        "Your browser blocked clipboard access. The link is in the address bar.",
      );
    }
  };

  return (
    <div className="space-y-8">
      {/* ------------------------------------------------------------- Verdict */}
      <Card className={cn("border", band.ring)}>
        <div className="flex flex-wrap items-start gap-5">
          <span
            aria-hidden="true"
            className="grid size-11 shrink-0 place-items-center rounded-full bg-surface-raised text-ink [&>svg]:size-5"
          >
            {band.icon}
          </span>

          <div className="min-w-[16rem] flex-1">
            <Eyebrow>Indicative assessment</Eyebrow>
            <h2
              ref={headingRef}
              tabIndex={-1}
              className="mt-1.5 text-h1 text-ink focus-visible:outline-none"
            >
              {assessment.band_label}
            </h2>
            <p className="mt-3 text-body leading-relaxed text-ink-muted measure">
              {assessment.band_explanation}
            </p>
          </div>

          {/* The number, deliberately subordinate to the words beside it. */}
          <div className="w-full max-w-xs shrink-0 rounded-lg border border-border bg-surface-raised p-4">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-micro uppercase text-ink-subtle">Rubric score</span>
              <Badge tone="neutral" size="sm">
                Indicative
              </Badge>
            </div>
            <p className="mt-1.5 flex items-baseline gap-1.5">
              <span className="text-[2rem] font-semibold leading-none tabular text-ink">
                {Math.round(assessment.indicative_score)}
              </span>
              <span className="text-small text-ink-subtle">/ 100</span>
            </p>
            <ProgressBar
              value={assessment.indicative_score}
              max={100}
              tone={band.tone}
              label={`Indicative fit score, ${Math.round(
                assessment.indicative_score,
              )} out of 100`}
              className="mt-3"
            />
            <p className="mt-3 text-[11px] leading-snug text-ink-subtle">
              {assessment.score_caveat}
            </p>
          </div>
        </div>

        {caps_applied.length > 0 && (
          <div className="mt-6 rounded-lg border border-caution/30 bg-caution-soft p-4">
            <div className="flex items-start gap-2.5">
              <AlertTriangle
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 text-caution"
              />
              <div>
                <h3 className="text-small font-medium text-ink">
                  The band was capped, not calculated
                </h3>
                <p className="mt-1 text-small text-ink-muted">
                  One or more hard limits in the rubric applied. These override the
                  weighted score, because a high score resting on a missing prerequisite
                  would mislead.
                </p>
                <ul className="mt-2.5 space-y-1.5">
                  {caps_applied.map((cap) => (
                    <li key={cap} className="text-small text-ink-muted">
                      — {cap}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        )}

        <Divider className="my-6" />

        <div className="flex flex-wrap items-center gap-2.5">
          <Button variant="secondary" onClick={() => void copyLink()} icon={<Link2 />}>
            Copy link
          </Button>
          <ReportDownload assessmentId={assessment.id} />
          <Button variant="ghost" onClick={onRestart} icon={<RotateCcw />}>
            Start over
          </Button>
          <span className="ml-auto text-small text-ink-subtle">
            Rubric {assessment.rubric_version} · generated by {assessment.generated_by}
          </span>
        </div>
      </Card>

      <Disclaimer title="What this assessment is, and is not">
        {assessment.disclaimer}
      </Disclaimer>

      {/* ------------------------------------------------------------ The detail */}
      <Tabs
        persistKey="fit-result.tab"
        items={[
          { id: "why", label: "Why this band" },
          {
            id: "requirements",
            label: "What it would require",
            count: assessment.technical_requirements.length,
          },
          {
            id: "gaps",
            label: "Where it does not fit",
            count: assessment.gaps.length,
          },
          {
            id: "questions",
            label: "Questions to ask",
            count: assessment.questions_for_sales.length,
          },
          { id: "architecture", label: "Your architecture" },
        ]}
      >
        {(active) => (
          <>
            {active === "why" && (
              <WhyPanel assessment={assessment} rubricUrl={rubric_definition_url} />
            )}
            {active === "requirements" && <RequirementsPanel assessment={assessment} />}
            {active === "gaps" && <GapsPanel gaps={assessment.gaps} />}
            {active === "questions" && (
              <QuestionsPanel questions={assessment.questions_for_sales} />
            )}
            {active === "architecture" && (
              <ArchitecturePanel architecture={architecture} legend={legend} />
            )}
          </>
        )}
      </Tabs>

      {/* ------------------------------------------------------------ Next step */}
      <Card tone="raised" className="border-accent-200">
        <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr] lg:items-center">
          <div>
            <Eyebrow as="h2">Recommended next step</Eyebrow>
            <h3 className="mt-2 text-h1 text-ink">{assessment.next_step}</h3>
            <p className="mt-3 text-small text-ink-muted measure">
              If you would rather keep looking on your own first, the playground runs real
              SQL against a synthetic lakehouse with no sign-up.
            </p>
          </div>
          <div className="flex flex-col gap-2.5">
            <Link href={`/request-demo?assessment=${assessment.id}`}>
              <Button variant="primary" size="lg" fullWidth icon={<CalendarCheck />}>
                Request a demo
              </Button>
            </Link>
            <Link href="/lakehouse-playground">
              <Button variant="secondary" size="lg" fullWidth iconRight={<ArrowRight />}>
                Open the playground
              </Button>
            </Link>
          </div>
        </div>

        {assessment.cited_source_detail.length > 0 && (
          <>
            <Divider className="my-6" />
            <SourceList
              sources={assessment.cited_source_detail}
              label="Every claim in this assessment traces to"
            />
          </>
        )}
      </Card>
    </div>
  );
}

// =====================================================================================
// Panels
// =====================================================================================

function WhyPanel({
  assessment,
  rubricUrl,
}: {
  assessment: FitAssessment;
  rubricUrl: string;
}) {
  const awarded = assessment.rubric.reduce((sum, entry) => sum + entry.awarded, 0);
  const total = assessment.rubric.reduce((sum, entry) => sum + entry.max, 0);

  return (
    <div className="space-y-6">
      <Card tone="flat">
        <Eyebrow as="h3">In summary</Eyebrow>
        <p className="mt-2.5 text-body leading-relaxed text-ink-muted measure">
          {assessment.requirement_summary}
        </p>
        {assessment.suitability_reasons.length > 0 && (
          <ul className="mt-5 space-y-2.5">
            {assessment.suitability_reasons.map((reason) => (
              <li key={reason} className="flex items-start gap-2.5">
                <CheckCircle2
                  aria-hidden="true"
                  className="mt-0.5 size-4 shrink-0 text-positive"
                />
                <span className="text-small text-ink-muted">{reason}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <RubricBreakdown
        entries={assessment.rubric}
        awarded={awarded}
        total={total}
        rubricUrl={rubricUrl}
      />
    </div>
  );
}

function RequirementsPanel({ assessment }: { assessment: FitAssessment }) {
  return (
    <div className="space-y-6">
      <p className="text-small text-ink-muted measure">
        IOMETE is self-hosted. These are the things you would have to provide or build,
        taken from IOMETE&rsquo;s own documentation. Nothing here is a COMPASS invention —
        each line cites where it came from.
      </p>
      <ul className="space-y-3">
        {assessment.technical_requirements.map((requirement) => (
          <li key={requirement.requirement}>
            <Card tone="flat">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <h3 className="text-small font-medium text-ink">
                  {requirement.requirement}
                </h3>
                <ClaimStatusBadge status={requirement.status} />
              </div>
              <p className="mt-2 text-small text-ink-muted">{requirement.detail}</p>
              {requirement.sources.length > 0 && (
                <div className="mt-2.5">
                  <SourceIds
                    ids={requirement.sources}
                    catalogue={assessment.cited_source_detail}
                    label="source"
                  />
                </div>
              )}
            </Card>
          </li>
        ))}
      </ul>

      {assessment.advantages.length > 0 && (
        <>
          <Divider />
          <div>
            <Eyebrow as="h3">And what you would gain</Eyebrow>
            <ul className="mt-3 space-y-3">
              {assessment.advantages.map((advantage) => (
                <li key={advantage.advantage}>
                  <Card tone="flat">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <h4 className="text-small font-medium text-ink">
                        {advantage.advantage}
                      </h4>
                      <ClaimStatusBadge status={advantage.status} />
                    </div>
                    <p className="mt-2 text-small text-ink-muted">{advantage.detail}</p>
                    {advantage.sources.length > 0 && (
                      <div className="mt-2.5">
                        <SourceIds
                          ids={advantage.sources}
                          catalogue={assessment.cited_source_detail}
                          label="source"
                        />
                      </div>
                    )}
                  </Card>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}

function GapsPanel({ gaps }: { gaps: FitGap[] }) {
  if (gaps.length === 0) {
    return (
      <Card tone="flat">
        <p className="text-small text-ink-muted measure">
          Your answers did not raise a specific gap against the rubric. That is not the same
          as there being none — it means nothing you told us triggered one. The questions
          tab is where to probe further.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <p className="text-small text-ink-muted measure">
        Listed plainly, with the mitigation where one exists. A vendor assessment that
        finds no problems is not an assessment.
      </p>
      <ul className="space-y-3">
        {gaps.map((gap) => (
          <li key={gap.gap}>
            <Card tone="flat">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <h3 className="text-small font-medium text-ink">{gap.gap}</h3>
                <Badge tone={SEVERITY_TONE[gap.severity]} size="sm">
                  {gap.severity} impact
                </Badge>
              </div>
              <p className="mt-2 text-small text-ink-muted">{gap.detail}</p>
              {gap.mitigation && (
                <p className="mt-2.5 flex items-start gap-2 rounded-md bg-surface-sunken p-2.5 text-small text-ink-muted">
                  <Wrench
                    aria-hidden="true"
                    className="mt-0.5 size-3.5 shrink-0 text-ink-subtle"
                  />
                  <span>
                    <span className="font-medium text-ink">Mitigation: </span>
                    {gap.mitigation}
                  </span>
                </p>
              )}
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}

function QuestionsPanel({ questions }: { questions: string[] }) {
  return (
    <div className="space-y-5">
      <p className="text-small text-ink-muted measure">
        COMPASS could not settle these from public documentation, and it will not guess.
        Put them to IOMETE directly — the answers change the assessment.
      </p>
      <Card tone="inverse">
        <ol className="space-y-3.5">
          {questions.map((question, index) => (
            <li key={question} className="flex items-start gap-3">
              <span
                aria-hidden="true"
                className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-graphite-800 text-[11px] font-semibold text-accent-400"
              >
                {index + 1}
              </span>
              <span className="text-small leading-relaxed text-ink-inverse-muted">
                {question}
              </span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

function ArchitecturePanel({
  architecture,
  legend,
}: {
  architecture: ArchitectureRecommendation;
  legend: GraphLegendEntry[];
}) {
  return (
    <div className="space-y-5">
      <div>
        <Eyebrow as="h3">Proposed placement</Eyebrow>
        <h4 className="mt-1.5 text-h2 text-ink">{architecture.title}</h4>
      </div>

      <Disclaimer title="How to read this diagram" tone="caution">
        {architecture.conceptual_disclaimer}
      </Disclaimer>

      {/* The legend travels with the graph: the canvas renders it beside the diagram,
          where a reader needs it, rather than as a separate block further down. */}
      <ArchitectureCanvas graph={{ ...architecture, legend }} />

      {architecture.narrative && (
        <Card tone="sunken">
          <Eyebrow as="h4">In words</Eyebrow>
          <div className="mt-2 space-y-3">
            {architecture.narrative.split("\n\n").map((paragraph) => (
              <p
                key={paragraph.slice(0, 40)}
                className="text-small leading-relaxed text-ink-muted measure"
              >
                {paragraph}
              </p>
            ))}
          </div>
        </Card>
      )}

      {architecture.integration_notes.length > 0 && (
        <Card>
          <Eyebrow as="h4">How each of your systems would connect</Eyebrow>
          <ul className="mt-3 divide-y divide-border">
            {architecture.integration_notes.map((note) => (
              <li key={note.system} className="py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-start justify-between gap-2.5">
                  <span className="text-small font-medium text-ink">{note.system}</span>
                  <NodeClaimBadge status={note.claim_status} />
                </div>
                <p className="mt-1 text-small text-ink-muted">{note.mechanism}</p>
                {note.note && (
                  <p className="mt-1 text-small text-ink-subtle">{note.note}</p>
                )}
                {note.sources.length > 0 && (
                  <div className="mt-1.5">
                    <SourceList sources={note.sources} inline label="source" />
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

// =====================================================================================
// Rubric
// =====================================================================================

/**
 * The rubric, shown in full.
 *
 * The defence against a misleading compatibility percentage is not hiding the number —
 * it is publishing the arithmetic, so a reader can disagree with a specific weighting
 * rather than with a black box.
 */
function RubricBreakdown({
  entries,
  awarded,
  total,
  rubricUrl,
}: {
  entries: RubricEntry[];
  awarded: number;
  total: number;
  rubricUrl: string;
}) {
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Eyebrow as="h3">How the score was reached</Eyebrow>
          <p className="mt-1.5 text-small text-ink-muted">
            {entries.length} weighted dimensions. {awarded.toFixed(1)} of{" "}
            {total.toFixed(1)} points awarded ({percent(total > 0 ? awarded / total : 0)}).
          </p>
        </div>
        <a
          href={rubricUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-small font-medium text-accent-700 underline decoration-accent-300 underline-offset-2 hover:decoration-accent-600 dark:text-accent-400"
        >
          Read the published rubric
        </a>
      </div>

      <ul className="mt-5 space-y-2.5">
        {entries.map((entry) => {
          const ratio = entry.max > 0 ? entry.awarded / entry.max : 0;
          const tone = ratio >= 0.75 ? "positive" : ratio >= 0.4 ? "caution" : "critical";
          return (
            <li key={entry.dimension}>
              <Disclosure
                summary={
                  <div className="flex w-full flex-wrap items-center gap-x-4 gap-y-2">
                    <span className="min-w-[10rem] flex-1 text-small font-medium text-ink">
                      {entry.label}
                    </span>
                    <span className="w-28 shrink-0">
                      <ProgressBar
                        value={entry.awarded}
                        max={entry.max}
                        tone={tone}
                        label={`${entry.label}: ${entry.awarded} of ${entry.max}`}
                      />
                    </span>
                    <span className="w-20 shrink-0 text-right text-small tabular text-ink-muted">
                      {entry.awarded.toFixed(1)} / {entry.max.toFixed(1)}
                    </span>
                  </div>
                }
              >
                <p className="text-small text-ink-muted measure">{entry.reasoning}</p>
                {entry.improves_with && (
                  <p className="mt-2.5 text-small text-ink-subtle measure">
                    <span className="font-medium text-ink-muted">
                      This score would rise if:{" "}
                    </span>
                    {entry.improves_with}
                  </p>
                )}
                <p className="mt-2.5 text-[11px] uppercase tracking-wide text-ink-subtle">
                  Weight {entry.weight} of {total}
                </p>
              </Disclosure>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

/**
 * Download the assessment as JSON.
 *
 * JSON rather than a generated PDF: the data is structured, the caveats travel with it,
 * and a glossy PDF invites the score being screenshotted away from its rubric — which is
 * the failure mode this whole page is built to avoid.
 */
function ReportDownload({ assessmentId }: { assessmentId: string }) {
  const [pending, setPending] = React.useState(false);
  const toast = useToast();

  const download = async () => {
    setPending(true);
    try {
      const { api } = await import("@/lib/api");
      const report = await api.fitReport(assessmentId);
      downloadFile(
        `iomete-fit-assessment-${assessmentId.slice(0, 8)}.json`,
        JSON.stringify(report, null, 2),
        "application/json",
      );
    } catch {
      toast.error(
        "Report could not be generated",
        "The assessment above is complete — only the download failed.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <Button
      variant="secondary"
      onClick={() => void download()}
      loading={pending}
      icon={<Download />}
    >
      Download the report
    </Button>
  );
}
