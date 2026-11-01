import { PublicSection } from "@/components/layout/PublicShell";
import { DemoRequestForm } from "@/components/features/prospects/DemoRequestForm";
import { Eyebrow } from "@/components/ui";

export const metadata = {
  title: "Request a demo",
  description:
    "Ask for a conversation with an IOMETE engineer, with your fit assessment attached " +
    "so the call starts from your environment rather than from discovery.",
};

/**
 * The demo request.
 *
 * Positioned as the end of the enablement journey rather than a gate in front of it:
 * everything on the public side — the explainer, the architecture, the playground, the
 * Fit Finder — works without giving us anything. This page is for the point at which a
 * person actually wants to talk to a person.
 */
export default function RequestDemoPage() {
  return (
    <>
      <div className="border-b border-border bg-surface-sunken">
        <PublicSection width="wide" className="py-14 sm:py-18">
          <div className="max-w-3xl">
            <Eyebrow as="h1">Talk to an engineer</Eyebrow>
            <h2 className="mt-3 text-h1 text-ink sm:text-display">
              Start the conversation with specifics
            </h2>
            <p className="mt-5 text-[1.0625rem] leading-relaxed text-ink-muted">
              Everything else on this site works without a form. This page exists for the
              point where you want a person — and if you have run the Fit Finder, that
              person can arrive already knowing your infrastructure, your constraints and
              the questions COMPASS could not answer from public documentation.
            </p>
          </div>
        </PublicSection>
      </div>

      <PublicSection width="wide" className="py-12 sm:py-16">
        <DemoRequestForm />
      </PublicSection>
    </>
  );
}
