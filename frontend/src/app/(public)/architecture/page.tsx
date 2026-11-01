import Link from "next/link";

import { ArrowRight, Cloud, HardDrive, Plug } from "lucide-react";

import { api } from "@/lib/api";
import type { ArchitectureGraph, ArchitecturePayload } from "@/lib/types";
import { groupBy } from "@/lib/utils";

import { PublicSection } from "@/components/layout/PublicShell";
import { ArchitectureCanvas } from "@/components/diagrams/ArchitectureCanvas";
import { InfrastructureForm } from "@/components/features/prospects/InfrastructureForm";
import {
  Badge,
  Button,
  Card,
  ClaimStatusBadge,
  Disclaimer,
  ErrorState,
  Eyebrow,
  SourceList,
} from "@/components/ui";

export const metadata = {
  title: "Architecture playground",
  description:
    "An interactive map of IOMETE's documented architecture, and how it would fit " +
    "around the infrastructure you already run.",
};

/**
 * The architecture playground.
 *
 * Two halves: IOMETE's own documented architecture (every component cited), and a
 * generator that places the visitor's stated systems around it. The second half is
 * deliberately labelled as conceptual throughout — it mixes verified product facts with
 * COMPASS's own proposal, and a reader must be able to tell which is which.
 */
export default async function ArchitecturePage() {
  let reference: ArchitectureGraph | null = null;
  let payload: ArchitecturePayload | null = null;
  let failure: Error | null = null;

  try {
    [reference, payload] = await Promise.all([
      api.referenceArchitecture(),
      api.architectureReference(),
    ]);
  } catch (caught) {
    failure = caught instanceof Error ? caught : new Error("Unknown error");
  }

  if (!reference || !payload) {
    return (
      <PublicSection className="py-20">
        <ErrorState error={failure ?? new Error("The architecture could not be loaded.")} />
      </PublicSection>
    );
  }

  const integrationsByCategory = groupBy(payload.integrations, (item) => item.category);
  const verifiedStorage = payload.storage_backends.filter(
    (backend) => backend.status === "verified",
  );
  const unconfirmedStorage = payload.storage_backends.filter(
    (backend) => backend.status !== "verified",
  );

  return (
    <>
      {/* ---------------------------------------------------------------- Hero */}
      <div className="border-b border-border bg-surface-sunken">
        <PublicSection width="wide" className="py-14 sm:py-18">
          <div className="max-w-3xl">
            <Eyebrow as="h1">Experience</Eyebrow>
            <h2 className="mt-3 text-h1 text-ink sm:text-display">
              How IOMETE fits around what you already run
            </h2>
            <p className="mt-5 text-[1.0625rem] leading-relaxed text-ink-muted">
              IOMETE does not replace your source databases or your BI tools. It sits
              between them, over storage you own. Click any component below to see what it
              does and why it is there.
            </p>
            <div className="mt-6 flex flex-wrap gap-2.5">
              <Badge tone="verified">
                {reference.nodes.filter((node) => node.claim_status === "documented").length}{" "}
                documented components
              </Badge>
              <Badge tone="neutral">{payload.architecture.tiers.length} tiers</Badge>
              <Badge tone="neutral">{payload.integrations.length} documented integrations</Badge>
            </div>
          </div>
        </PublicSection>
      </div>

      {/* ----------------------------------------------------- The reference */}
      <PublicSection width="wide" className="py-14 sm:py-18" id="reference">
        <div className="max-w-2xl">
          <Eyebrow as="h2">The platform</Eyebrow>
          <h3 className="mt-3 text-h1 text-ink">IOMETE&rsquo;s documented architecture</h3>
          <p className="mt-4 text-body text-ink-muted measure">
            {payload.architecture.summary}
          </p>
        </div>

        <Disclaimer title="What is documented and what is illustrative" className="mt-6">
          {reference.conceptual_disclaimer}
        </Disclaimer>

        <div className="mt-7">
          <ArchitectureCanvas graph={reference} />
        </div>

        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {[...payload.architecture.tiers]
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((tier) => (
              <Card key={tier.id} tone="flat">
                <h4 className="text-h3 text-ink">{tier.name}</h4>
                <p className="mt-2 text-small text-ink-muted">{tier.description}</p>
                <p className="mt-3 text-micro uppercase text-ink-subtle">
                  {tier.components.length} components
                </p>
              </Card>
            ))}
        </div>
      </PublicSection>

      {/* ---------------------------------------------------- Generate yours */}
      <div className="border-y border-border bg-surface-sunken">
        <PublicSection width="wide" className="py-14 sm:py-18" id="generate">
          <div className="max-w-2xl">
            <Eyebrow as="h2">Your architecture</Eyebrow>
            <h3 className="mt-3 text-h1 text-ink">Put your own systems in it</h3>
            <p className="mt-4 text-body text-ink-muted measure">
              Four questions. COMPASS will place what you run around IOMETE&rsquo;s
              documented components and say, for each one, how it would actually connect —
              including where that connection needs confirming.
            </p>
          </div>
          <div className="mt-7">
            <InfrastructureForm />
          </div>
        </PublicSection>
      </div>

      {/* --------------------------------------------------- Storage options */}
      <PublicSection width="wide" className="py-14 sm:py-18" id="storage">
        <div className="grid gap-10 lg:grid-cols-[1fr_1fr] lg:gap-14">
          <div>
            <div className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="grid size-8 place-items-center rounded-md bg-accent-50 text-accent-700 [&>svg]:size-4 dark:text-accent-300"
              >
                <HardDrive />
              </span>
              <Eyebrow as="h2">Storage</Eyebrow>
            </div>
            <h3 className="mt-3 text-h2 text-ink">Your bucket, your account</h3>
            <p className="mt-3 text-small text-ink-muted measure">
              All table data, Spark event logs and SQL results live in object storage you
              control. Compute and storage are decoupled, which is what makes a lakehouse
              cheap to keep and independently scalable.
            </p>

            <ul className="mt-5 space-y-2">
              {verifiedStorage.map((backend) => (
                <li
                  key={backend.name}
                  className="flex flex-wrap items-center gap-2.5 rounded-md border border-border bg-surface-raised px-3 py-2"
                >
                  <span className="text-small font-medium text-ink">{backend.name}</span>
                  {backend.scheme && (
                    <code className="rounded border border-border bg-surface-sunken px-1.5 py-0.5 font-mono text-[0.75rem] text-ink-muted">
                      {backend.scheme}
                    </code>
                  )}
                  <span className="ml-auto">
                    <ClaimStatusBadge status={backend.status} />
                  </span>
                </li>
              ))}
            </ul>

            {unconfirmedStorage.length > 0 && (
              <Card tone="sunken" className="mt-4 border-caution/30">
                <Eyebrow as="h4">Listed but not documented as a storage type</Eyebrow>
                <ul className="mt-2.5 space-y-2">
                  {unconfirmedStorage.map((backend) => (
                    <li key={backend.name} className="text-small">
                      <span className="font-medium text-ink">{backend.name}</span>
                      {backend.note && (
                        <span className="text-ink-muted"> — {backend.note}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>

          <div>
            <div className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="grid size-8 place-items-center rounded-md bg-accent-50 text-accent-700 [&>svg]:size-4 dark:text-accent-300"
              >
                <Cloud />
              </span>
              <Eyebrow as="h2">Deployment</Eyebrow>
            </div>
            <h3 className="mt-3 text-h2 text-ink">Wherever your data has to live</h3>
            <p className="mt-3 text-small text-ink-muted measure">
              The same Helm chart into a Kubernetes cluster you provide. The differences
              between these are operational, not architectural.
            </p>

            <dl className="mt-5 space-y-3">
              {payload.deployment_models.map((model) => (
                <div
                  key={model.id}
                  className="rounded-md border border-border bg-surface-raised p-3.5"
                >
                  <dt className="flex flex-wrap items-center justify-between gap-2.5">
                    <span className="text-small font-medium text-ink">{model.name}</span>
                    <ClaimStatusBadge status={model.status} />
                  </dt>
                  <dd className="mt-1.5 text-small text-ink-muted">{model.description}</dd>
                  <dd className="mt-1.5 text-small text-ink-subtle">
                    <span className="font-medium">Best for: </span>
                    {model.best_for}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </PublicSection>

      {/* ---------------------------------------------------- Integrations */}
      <div className="border-y border-border bg-surface-sunken">
        <PublicSection width="wide" className="py-14 sm:py-18" id="integrations">
          <div className="max-w-2xl">
            <div className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="grid size-8 place-items-center rounded-md bg-accent-50 text-accent-700 [&>svg]:size-4 dark:text-accent-300"
              >
                <Plug />
              </span>
              <Eyebrow as="h2">Integrations</Eyebrow>
            </div>
            <h3 className="mt-3 text-h1 text-ink">What IOMETE documents connecting to</h3>
            <p className="mt-4 text-body text-ink-muted measure">
              Only integrations IOMETE actually documents are listed. If something you rely
              on is missing, that does not mean it cannot work — it means COMPASS will not
              claim it does.
            </p>
          </div>

          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(integrationsByCategory)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([category, items]) => (
                <Card key={category} tone="flat">
                  <h4 className="text-micro uppercase text-ink-subtle">{category}</h4>
                  <ul className="mt-3 flex flex-wrap gap-1.5">
                    {items.map((item) => (
                      <li key={item.name}>
                        <Badge
                          tone={item.status === "verified" ? "verified" : "caution"}
                          size="sm"
                        >
                          {item.name}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                </Card>
              ))}
          </div>

          <p className="mt-6 text-small text-ink-subtle">
            <SourceList sources={payload.architecture.sources} inline label="Architecture read from" />
          </p>
        </PublicSection>
      </div>

      {/* ------------------------------------------------------------ Closing */}
      <PublicSection width="wide" className="py-14 sm:py-18">
        <Card tone="raised" className="border-accent-200">
          <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr] lg:items-center">
            <div>
              <h2 className="text-h1 text-ink">Seen enough of the shape?</h2>
              <p className="mt-3 text-body text-ink-muted measure">
                Run the Fit Finder for an indicative assessment with a downloadable report,
                or go and type SQL into a working lakehouse.
              </p>
            </div>
            <div className="flex flex-col gap-2.5">
              <Link href="/fit-finder">
                <Button variant="primary" size="lg" fullWidth iconRight={<ArrowRight />}>
                  Run the Fit Finder
                </Button>
              </Link>
              <Link href="/lakehouse-playground">
                <Button variant="secondary" size="lg" fullWidth>
                  Open the playground
                </Button>
              </Link>
            </div>
          </div>
        </Card>
      </PublicSection>
    </>
  );
}
