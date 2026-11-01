import { api } from "@/lib/api";
import type { FitRubricDefinition } from "@/lib/types";

import { PublicSection } from "@/components/layout/PublicShell";
import { FitFinderExperience } from "@/components/features/prospects/FitFinderExperience";
import { Badge, Card, Disclaimer, Eyebrow, SourceList } from "@/components/ui";

export const metadata = {
  title: "Fit Finder",
  description:
    "An indicative assessment of whether IOMETE suits your infrastructure, scored " +
    "against a published rubric that tells you plainly where it would not fit.",
};

/**
 * The Fit Finder.
 *
 * The rubric is fetched on the server and rendered on the page *before* anyone answers a
 * question. That ordering is the point: a prospect can read exactly how they are about to
 * be scored, and the weightings, before giving us anything. An assessment tool that
 * publishes its rubric cannot quietly flatter the vendor.
 */
export default async function FitFinderPage() {
  let rubric: FitRubricDefinition | null = null;
  try {
    rubric = await api.fitRubric();
  } catch {
    // Non-fatal: the wizard posts its own request and does not depend on this. The rubric
    // panel simply does not render, rather than taking the page down with it.
    rubric = null;
  }

  return (
    <>
      {/* ---------------------------------------------------------------- Hero */}
      <div className="border-b border-border bg-surface-sunken">
        <PublicSection width="wide" className="py-14 sm:py-18">
          <div className="max-w-3xl">
            <Eyebrow as="h1">Assess</Eyebrow>
            <h2 className="mt-3 text-h1 text-ink sm:text-display">
              Would IOMETE actually fit you?
            </h2>
            <p className="mt-5 text-[1.0625rem] leading-relaxed text-ink-muted">
              Ten questions, about four minutes. You will get a band, the rubric that
              produced it, the technical requirements IOMETE would place on you, and a
              frank list of where it would not fit. No sign-up, and no contact details
              unless you want to be contacted.
            </p>
            <div className="mt-6 flex flex-wrap gap-2.5">
              <Badge tone="neutral">Indicative, not a quotation</Badge>
              {rubric && <Badge tone="neutral">Rubric {rubric.version}</Badge>}
              <Badge tone="verified">Every claim sourced</Badge>
            </div>
          </div>
        </PublicSection>
      </div>

      {/* -------------------------------------------------------------- Wizard */}
      <PublicSection width="wide" className="py-12 sm:py-16">
        <FitFinderExperience />
      </PublicSection>

      {/* -------------------------------------------------------------- Rubric */}
      {rubric && (
        <div className="border-t border-border bg-surface-sunken">
          <PublicSection width="wide" className="py-14 sm:py-18" id="rubric">
            <div className="max-w-2xl">
              <Eyebrow as="h2">The rubric, in advance</Eyebrow>
              <h3 className="mt-3 text-h1 text-ink">How you are about to be scored</h3>
              <p className="mt-4 text-body text-ink-muted measure">
                Published before you answer anything, because a scoring tool whose weights
                are hidden is a marketing device. Version {rubric.version}, total weight{" "}
                {rubric.total_weight}.
              </p>
            </div>

            <Disclaimer title="On the number this produces" className="mt-6">
              {rubric.disclaimer}
            </Disclaimer>

            <div className="mt-8 grid gap-8 lg:grid-cols-[1.3fr_1fr] lg:gap-12">
              <div>
                <Eyebrow as="h3">Dimensions and weights</Eyebrow>
                <ul className="mt-3.5 space-y-2.5">
                  {[...rubric.dimensions]
                    .sort((a, b) => b.weight - a.weight)
                    .map((dimension) => (
                      <li key={dimension.key}>
                        <Card tone="flat">
                          <div className="flex flex-wrap items-baseline justify-between gap-2.5">
                            <h4 className="text-small font-medium text-ink">
                              {dimension.label}
                            </h4>
                            <span className="text-small tabular text-ink-subtle">
                              weight {dimension.weight}
                            </span>
                          </div>
                          <p className="mt-1.5 text-small text-ink-muted">
                            {dimension.what_it_measures}
                          </p>
                        </Card>
                      </li>
                    ))}
                </ul>
              </div>

              <div className="space-y-6">
                <div>
                  <Eyebrow as="h3">Bands</Eyebrow>
                  <dl className="mt-3.5 space-y-2.5">
                    {rubric.bands.map((band) => (
                      <div
                        key={band.band}
                        className="rounded-md border border-border bg-surface-raised p-3.5"
                      >
                        <dt className="flex flex-wrap items-baseline justify-between gap-2">
                          <span className="text-small font-medium text-ink">
                            {band.label}
                          </span>
                          <span className="text-micro tabular text-ink-subtle">
                            {rubric.band_thresholds[band.band] ?? "—"}
                          </span>
                        </dt>
                        <dd className="mt-1.5 text-small text-ink-muted">
                          {band.explanation}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>

                {rubric.hard_caps.length > 0 && (
                  <Card tone="sunken" className="border-caution/30">
                    <Eyebrow as="h3">Hard caps</Eyebrow>
                    <p className="mt-1.5 text-small text-ink-muted">
                      These override the weighted score entirely. A good total built on a
                      missing prerequisite is worse than no score at all.
                    </p>
                    <ul className="mt-3 space-y-2">
                      {rubric.hard_caps.map((cap) => (
                        <li key={cap} className="text-small text-ink-muted">
                          — {cap}
                        </li>
                      ))}
                    </ul>
                  </Card>
                )}

                {rubric.sources.length > 0 && (
                  <SourceList
                    sources={rubric.sources}
                    label="The requirements behind these weights come from"
                  />
                )}
              </div>
            </div>
          </PublicSection>
        </div>
      )}
    </>
  );
}
