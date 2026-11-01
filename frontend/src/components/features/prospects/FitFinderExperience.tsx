"use client";

import * as React from "react";

import { useRouter, useSearchParams } from "next/navigation";

import { api } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import type { FitAssessmentResponse } from "@/lib/types";

import { FitFinderWizard } from "./FitFinderWizard";
import { FitResult } from "./FitResult";
import { ErrorState, LoadingState, SkeletonCard } from "@/components/ui";

const RUBRIC_URL = "/api/v1/fit-assessments/rubric/";

/**
 * The Fit Finder's interactive half.
 *
 * Owns one piece of state — the assessment, or none — and owns the URL. On completion it
 * writes `?assessment=<id>` so the result survives a refresh and can be sent to a
 * colleague; on load it reads that parameter back and rebuilds the result from the two
 * public endpoints. Somebody who has answered ten questions should never lose the answer
 * to a stray reload.
 */
export function FitFinderExperience() {
  // `useSearchParams` opts the subtree into client-side rendering, so the boundary has to
  // be here rather than at the page.
  return (
    <React.Suspense fallback={<SkeletonCard />}>
      <FitFinderInner />
    </React.Suspense>
  );
}

function FitFinderInner() {
  const router = useRouter();
  const params = useSearchParams();
  const resumeId = params.get("assessment");

  /** Set when this session generated the result, so it is not refetched. */
  const [fresh, setFresh] = React.useState<FitAssessmentResponse | null>(null);

  // Rebuilding from a shared link. Both endpoints are public and keyed by an unguessable
  // id, which is the prospect's own way back to their assessment.
  const needsFetch = Boolean(resumeId) && fresh?.assessment.id !== resumeId;
  const resumed = useResource<FitAssessmentResponse>(
    async () => {
      const id = resumeId!;
      const [assessment, architecture] = await Promise.all([
        api.fitAssessment(id),
        api.fitArchitecture(id),
      ]);
      const { legend, ...recommendation } = architecture;
      return {
        assessment,
        architecture: recommendation,
        legend,
        // Persisted on the assessment, so a reopened link shows the same capped-band
        // reasoning as the original run rather than silently dropping it.
        caps_applied: assessment.caps_applied,
        rubric_definition_url: RUBRIC_URL,
      };
    },
    [resumeId],
    { enabled: needsFetch },
  );

  const onComplete = (next: FitAssessmentResponse) => {
    setFresh(next);
    // `replace`, not `push`: Back should return to where they came from, not to a
    // half-filled wizard. `scroll: false` because FitResult moves focus to its own
    // heading, which brings it into view precisely.
    router.replace(`/fit-finder?assessment=${next.assessment.id}`, { scroll: false });
  };

  const onRestart = () => {
    setFresh(null);
    router.replace("/fit-finder", { scroll: false });
  };

  const result = fresh?.assessment.id === resumeId ? fresh : resumed.data;

  if (needsFetch && resumed.error && !resumed.data) {
    return (
      <div className="space-y-4">
        <ErrorState error={resumed.error} onRetry={onRestart} />
        <p className="text-small text-ink-muted">
          That link may be mistyped, or the assessment may have been removed. Running a new
          one takes about four minutes.
        </p>
      </div>
    );
  }

  if (needsFetch && resumed.loading && !result) {
    return <LoadingState label="Opening your assessment" />;
  }

  if (result) {
    return <FitResult result={result} onRestart={onRestart} />;
  }

  return <FitFinderWizard onComplete={onComplete} />;
}
