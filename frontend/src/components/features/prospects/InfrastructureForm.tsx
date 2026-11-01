"use client";

import * as React from "react";

import { RotateCcw, Wand2 } from "lucide-react";

import { api } from "@/lib/api";
import { useMutation } from "@/lib/hooks";
import type { ArchitectureGraph, FitAnswers } from "@/lib/types";

import { ArchitectureCanvas } from "@/components/diagrams/ArchitectureCanvas";
import {
  Button,
  Card,
  Disclaimer,
  Eyebrow,
  FormError,
  NodeClaimBadge,
  Select,
  SourceList,
  TagInput,
} from "@/components/ui";

const SYSTEM_SUGGESTIONS = [
  "PostgreSQL",
  "MySQL",
  "Oracle",
  "SQL Server",
  "Snowflake",
  "BigQuery",
  "S3",
  "MinIO",
  "Apache Ozone",
  "Azure Data Lake Storage Gen2",
  "Kafka",
  "Airflow",
  "dbt",
  "CSV files",
  "APIs",
];

const BI_SUGGESTIONS = [
  "Power BI",
  "Tableau",
  "Metabase",
  "Apache Superset",
  "Looker",
  "Redash",
  "ThoughtSpot",
  "Excel",
];

const LOCATIONS = [
  { value: "on_premises", label: "Entirely on-premises" },
  { value: "private_cloud", label: "Private cloud" },
  { value: "public_cloud", label: "Public cloud" },
  { value: "hybrid", label: "Hybrid — on-premises and cloud" },
  { value: "air_gapped", label: "Air-gapped / isolated network" },
  { value: "undecided", label: "Not decided yet" },
];

const CLOUDS = [
  { value: "", label: "Not applicable" },
  { value: "aws", label: "AWS" },
  { value: "azure", label: "Azure" },
  { value: "gcp", label: "Google Cloud" },
];

const USE_CASES = [
  { value: "consolidation", label: "Consolidating a lake and a warehouse" },
  { value: "bi_reporting", label: "BI and reporting" },
  { value: "data_engineering", label: "Data engineering and ETL" },
  { value: "real_time", label: "Real-time analytics" },
  { value: "ai_ml", label: "AI and machine learning" },
  { value: "data_science", label: "Data science and exploration" },
  { value: "governance", label: "Governance and compliance reporting" },
  { value: "data_mesh", label: "Data mesh / domain ownership" },
  { value: "other", label: "Something else" },
];

const VOLUMES = [
  { value: "under_1tb", label: "Under 1 TB" },
  { value: "tb_1_10", label: "1–10 TB" },
  { value: "tb_10_100", label: "10–100 TB" },
  { value: "tb_100_1pb", label: "100 TB – 1 PB" },
  { value: "over_1pb", label: "Over 1 PB" },
  { value: "unknown", label: "Not sure" },
];

/**
 * Generate a personalised architecture from a handful of inputs.
 *
 * A short form on purpose — four questions, not the full Fit Finder. Someone exploring the
 * architecture page wants to see their own systems in the picture, not to complete an
 * assessment. The Fit Finder is one click away for anyone who wants the long version.
 */
export function InfrastructureForm() {
  const [systems, setSystems] = React.useState<string[]>([]);
  const [biTools, setBiTools] = React.useState<string[]>([]);
  const [location, setLocation] = React.useState("hybrid");
  const [cloud, setCloud] = React.useState("");
  const [useCase, setUseCase] = React.useState("consolidation");
  const [volume, setVolume] = React.useState("tb_10_100");
  const [graph, setGraph] = React.useState<ArchitectureGraph | null>(null);

  const generate = useMutation(
    async (answers: Partial<FitAnswers>) => api.generateArchitecture(answers),
    { onSuccess: setGraph },
  );

  const onSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    void generate.run({
      current_systems: systems,
      bi_tools: biTools,
      infrastructure_location: location,
      cloud_providers: cloud ? [cloud] : [],
      primary_use_case: useCase,
      data_volume: volume,
    });
  };

  const reset = () => {
    setGraph(null);
    generate.reset();
  };

  return (
    <div className="space-y-6">
      {!graph && (
        <Card>
          <Eyebrow as="h3">Your estate</Eyebrow>
          <h4 className="mt-2 text-h2 text-ink">
            See your own systems in the picture
          </h4>
          <p className="mt-2 text-small text-ink-muted measure">
            Tell us roughly what you run and COMPASS will place it around IOMETE&rsquo;s
            documented architecture. Anything it cannot verify a connector for will be
            labelled as a conceptual placement rather than presented as an integration.
          </p>

          <form onSubmit={onSubmit} className="mt-6 space-y-5">
            <TagInput
              label="Databases, storage and warehouses you use today"
              description="Type and press Enter, or pick from the common ones."
              placeholder="e.g. PostgreSQL"
              values={systems}
              onChange={setSystems}
              suggestions={SYSTEM_SUGGESTIONS}
            />

            <TagInput
              label="BI and analysis tools that must keep working"
              placeholder="e.g. Power BI"
              values={biTools}
              onChange={setBiTools}
              suggestions={BI_SUGGESTIONS}
            />

            <div className="grid gap-4 sm:grid-cols-2">
              <Select
                label="Where would IOMETE run?"
                options={LOCATIONS}
                value={location}
                onChange={(event) => setLocation(event.target.value)}
              />
              <Select
                label="Cloud provider"
                description="Determines the storage backend shown."
                options={CLOUDS}
                value={cloud}
                onChange={(event) => setCloud(event.target.value)}
              />
              <Select
                label="Primary use case"
                options={USE_CASES}
                value={useCase}
                onChange={(event) => setUseCase(event.target.value)}
              />
              <Select
                label="Roughly how much data?"
                options={VOLUMES}
                value={volume}
                onChange={(event) => setVolume(event.target.value)}
              />
            </div>

            <FormError error={generate.error} />

            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={generate.pending}
              icon={<Wand2 />}
            >
              Generate my architecture
            </Button>
          </form>
        </Card>
      )}

      {graph && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <Eyebrow as="h3">Proposed architecture</Eyebrow>
              <h4 className="mt-1.5 text-h2 text-ink">{graph.title}</h4>
            </div>
            <Button variant="secondary" onClick={reset} icon={<RotateCcw />}>
              Change my inputs
            </Button>
          </div>

          <Disclaimer title="How to read this diagram" tone="caution">
            {graph.conceptual_disclaimer}
          </Disclaimer>

          <ArchitectureCanvas graph={graph} />

          {graph.narrative && (
            <Card tone="sunken">
              <Eyebrow as="h4">In words</Eyebrow>
              <div className="mt-2 space-y-3">
                {graph.narrative.split("\n\n").map((paragraph) => (
                  <p key={paragraph.slice(0, 40)} className="text-small text-ink-muted measure">
                    {paragraph}
                  </p>
                ))}
              </div>
            </Card>
          )}

          {graph.integration_notes.length > 0 && (
            <Card>
              <Eyebrow as="h4">How each of your systems would connect</Eyebrow>
              <ul className="mt-3 divide-y divide-border">
                {graph.integration_notes.map((note) => (
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

          {graph.open_questions.length > 0 && (
            <Card tone="inverse">
              <Eyebrow as="h4" className="text-accent-400">
                Open questions
              </Eyebrow>
              <p className="mt-1.5 text-small text-ink-inverse-muted">
                COMPASS could not settle these from public documentation. They are the
                right things to ask IOMETE directly.
              </p>
              <ul className="mt-3.5 space-y-2.5">
                {graph.open_questions.map((question, index) => (
                  <li key={question} className="flex items-start gap-3">
                    <span
                      aria-hidden="true"
                      className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-graphite-800 text-[11px] font-semibold text-accent-400"
                    >
                      {index + 1}
                    </span>
                    <span className="text-small text-ink-inverse-muted">{question}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
