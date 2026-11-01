import Link from "next/link";

import { ArrowRight, Database, Workflow } from "lucide-react";

import { api } from "@/lib/api";
import type { DatasetPayload, PlaygroundStatus, SampleQuery } from "@/lib/types";
import { compactNumber, formatDate, number } from "@/lib/utils";

import { PublicSection } from "@/components/layout/PublicShell";
import { PipelineStages } from "@/components/features/lakehouse/PipelineStages";
import { SchemaBrowser } from "@/components/features/lakehouse/SchemaBrowser";
import { SqlConsole } from "@/components/features/lakehouse/SqlConsole";
import {
  Badge,
  Button,
  Card,
  ErrorState,
  Eyebrow,
  IntegrationModeBadge,
  KeyValueGrid,
  SimulatedNotice,
} from "@/components/ui";

export const metadata = {
  title: "Lakehouse playground",
  description:
    "Run real SQL against a synthetic Iceberg-style dataset and see what a lakehouse " +
    "actually does — partition pruning, snapshots, schema evolution and the query plan.",
};

/**
 * The lakehouse playground.
 *
 * Three honest claims, labelled separately because they are separately true: the SQL
 * genuinely executes, the dataset is synthetic, and the Iceberg metadata and execution
 * plan are illustrative teaching devices rather than readings from a live cluster. Every
 * surface below states whichever of those applies to it. Nothing here implies a
 * connection to a real IOMETE deployment, because there is none.
 */
export default async function PlaygroundPage() {
  let status: PlaygroundStatus | null = null;
  let dataset: DatasetPayload | null = null;
  let samples: SampleQuery[] = [];
  let failure: Error | null = null;

  try {
    const [statusResult, datasetResult, samplesResult] = await Promise.all([
      api.playgroundStatus(),
      api.dataset(),
      api.sampleQueries(),
    ]);
    status = statusResult;
    dataset = datasetResult;
    samples = samplesResult.queries;
  } catch (caught) {
    failure = caught instanceof Error ? caught : new Error("Unknown error");
  }

  if (!status || !dataset) {
    return (
      <PublicSection className="py-20">
        <ErrorState error={failure ?? new Error("The playground could not be loaded.")} />
      </PublicSection>
    );
  }

  return (
    <>
      {/* ---------------------------------------------------------------- Hero */}
      <div className="border-b border-border bg-surface-sunken">
        <PublicSection width="wide" className="py-14 sm:py-18">
          <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr] lg:gap-12">
            <div>
              <Eyebrow as="h1">Experience</Eyebrow>
              <h2 className="mt-3 text-h1 text-ink sm:text-display">
                Type SQL into a lakehouse
              </h2>
              <p className="mt-5 text-[1.0625rem] leading-relaxed text-ink-muted">
                No sign-up, no cluster, no credentials. The queries below really run — in a
                read-only sandbox, over a synthetic dataset — and each guided example
                demonstrates something specific about why a lakehouse behaves the way it
                does.
              </p>
              <div className="mt-6 flex flex-wrap items-center gap-2.5">
                <IntegrationModeBadge mode={status.adapter.mode} />
                <Badge tone="neutral">{dataset.tables.length} tables</Badge>
                <Badge tone="neutral">{compactNumber(dataset.total_rows)} rows</Badge>
                <Badge tone="neutral">{samples.length} guided queries</Badge>
              </div>
            </div>

            <Card tone="raised">
              <Eyebrow as="h2">What is and is not real here</Eyebrow>
              <dl className="mt-3.5 space-y-3">
                <div>
                  <dt className="text-small font-medium text-ink">
                    The SQL execution is real
                  </dt>
                  <dd className="mt-0.5 text-small text-ink-muted">
                    {status.sql_execution_note}
                  </dd>
                </div>
                <div>
                  <dt className="text-small font-medium text-ink">The data is synthetic</dt>
                  <dd className="mt-0.5 text-small text-ink-muted">
                    Generated deterministically from a fixed seed. It is not any real
                    company&rsquo;s data.
                  </dd>
                </div>
                <div>
                  <dt className="text-small font-medium text-ink">
                    The Iceberg metadata is illustrative
                  </dt>
                  <dd className="mt-0.5 text-small text-ink-muted">
                    Snapshots, manifests and the query plan are teaching devices — not read
                    from a live IOMETE deployment.
                  </dd>
                </div>
              </dl>
            </Card>
          </div>
        </PublicSection>
      </div>

      {/* ------------------------------------------------------------- Console */}
      <PublicSection width="wide" className="py-12 sm:py-14" id="console">
        <SimulatedNotice className="mb-6">{dataset.synthetic_notice}</SimulatedNotice>
        <SqlConsole samples={samples} status={status} />
      </PublicSection>

      {/* -------------------------------------------------------------- Schema */}
      <div className="border-y border-border bg-surface-sunken">
        <PublicSection width="wide" className="py-14 sm:py-18" id="schema">
          <div className="max-w-2xl">
            <div className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="grid size-8 place-items-center rounded-md bg-accent-50 text-accent-700 [&>svg]:size-4 dark:text-accent-300"
              >
                <Database />
              </span>
              <Eyebrow as="h2">The dataset</Eyebrow>
            </div>
            <h3 className="mt-3 text-h1 text-ink">{dataset.label}</h3>
            <p className="mt-4 text-body text-ink-muted measure">{dataset.description}</p>
          </div>

          <KeyValueGrid
            className="mt-6"
            columns={4}
            entries={[
              { label: "Tables", value: number(dataset.tables.length) },
              { label: "Total rows", value: number(dataset.total_rows) },
              {
                label: "Date range",
                value: `${formatDate(dataset.date_range.from)} – ${formatDate(
                  dataset.date_range.to,
                )}`,
              },
              { label: "Dataset id", value: dataset.dataset_id },
            ]}
          />

          <div className="mt-8">
            <SchemaBrowser tables={dataset.tables} />
          </div>
        </PublicSection>
      </div>

      {/* ------------------------------------------------------------ Pipeline */}
      <PublicSection width="wide" className="py-14 sm:py-18" id="pipeline">
        <div className="grid gap-10 lg:grid-cols-[1fr_1.2fr] lg:gap-14">
          <div className="lg:sticky lg:top-24 lg:self-start">
            <div className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="grid size-8 place-items-center rounded-md bg-accent-50 text-accent-700 [&>svg]:size-4 dark:text-accent-300"
              >
                <Workflow />
              </span>
              <Eyebrow as="h2">End to end</Eyebrow>
            </div>
            <h3 className="mt-3 text-h1 text-ink">
              What happens between a file landing and an answer
            </h3>
            <p className="mt-4 text-body text-ink-muted measure">
              A query that returns in a second passed through seven stages. Knowing the
              stages is what lets you reason about where cost, latency and access control
              actually come from — and each one names the IOMETE component responsible.
            </p>
            <div className="mt-6 flex flex-col gap-2.5 sm:flex-row lg:flex-col">
              <Link href="/architecture">
                <Button variant="secondary" fullWidth iconRight={<ArrowRight />}>
                  See these as an architecture
                </Button>
              </Link>
              <Link href="/fit-finder">
                <Button variant="primary" fullWidth>
                  Check whether it fits us
                </Button>
              </Link>
            </div>
          </div>

          <PipelineStages stages={dataset.pipeline} />
        </div>
      </PublicSection>

      {/* ------------------------------------------------------- What's missing */}
      <div className="border-t border-border bg-surface-sunken">
        <PublicSection width="wide" className="py-14 sm:py-18">
          <div className="grid gap-8 lg:grid-cols-2 lg:gap-12">
            <div>
              <Eyebrow as="h2">What this demo can do</Eyebrow>
              <ul className="mt-3.5 space-y-2.5">
                {status.adapter.capabilities.map((capability) => (
                  <li key={capability} className="flex items-start gap-2.5">
                    <span
                      aria-hidden="true"
                      className="mt-[0.45rem] size-1.5 shrink-0 rounded-full bg-positive"
                    />
                    <span className="text-small text-ink-muted">{capability}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <Eyebrow as="h2">And what it cannot</Eyebrow>
              <ul className="mt-3.5 space-y-2.5">
                {status.adapter.limitations.map((limitation) => (
                  <li key={limitation} className="flex items-start gap-2.5">
                    <span
                      aria-hidden="true"
                      className="mt-[0.45rem] size-1.5 shrink-0 rounded-full bg-caution"
                    />
                    <span className="text-small text-ink-muted">{limitation}</span>
                  </li>
                ))}
              </ul>
              {status.adapter.missing_configuration.length > 0 && (
                <Card tone="sunken" className="mt-5">
                  <Eyebrow as="h3">To read a live catalogue instead</Eyebrow>
                  <ul className="mt-2.5 space-y-2">
                    {status.adapter.missing_configuration.map((item) => (
                      <li key={item} className="text-small text-ink-muted">
                        {item}
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
            </div>
          </div>
        </PublicSection>
      </div>
    </>
  );
}
