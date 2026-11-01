import { PublicSection } from "@/components/layout/PublicShell";
import { CallPrep } from "@/components/features/prospects/CallPrep";
import { Badge, Eyebrow } from "@/components/ui";

export const metadata = {
  title: "Call prep",
  description:
    "A sales-call brief built from IOMETE's public documentation in fifteen seconds — " +
    "with every claim labelled sourced, assumed or not documented.",
};

/**
 * Call preparation.
 *
 * The one page aimed at the sales rep rather than the buyer. The friction it removes is
 * specific and measurable: fifteen minutes before a call, work out what this buyer will
 * ask, which of it IOMETE's documentation answers, and — the part no generic assistant
 * does — which of it must not be answered at all.
 */
export default function CallPrepPage() {
  return (
    <>
      <div className="border-b border-border bg-surface-sunken print:hidden">
        <PublicSection width="wide" className="py-14 sm:py-18">
          <div className="max-w-3xl">
            <Eyebrow as="h1">For the call</Eyebrow>
            <h2 className="mt-3 text-h1 text-ink sm:text-display">
              Your call is in fifteen minutes
            </h2>
            <p className="mt-5 text-[1.0625rem] leading-relaxed text-ink-muted">
              Type what you know about the company. Get back what they will ask, what to
              lead with, what not to claim, and an honest count of what IOMETE&rsquo;s
              public documentation does not answer.
            </p>
            <div className="mt-6 flex flex-wrap gap-2.5">
              <Badge tone="verified">Every claim labelled</Badge>
              <Badge tone="gated">Unknowns counted, not written around</Badge>
              <Badge tone="neutral">No language model</Badge>
            </div>
          </div>
        </PublicSection>
      </div>

      <PublicSection width="wide" className="py-12 sm:py-16">
        <CallPrep />
      </PublicSection>
    </>
  );
}
