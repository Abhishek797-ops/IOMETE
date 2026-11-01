"use client";

import * as React from "react";

import { Database, KeyRound, Layers3, Table2 } from "lucide-react";

import type { DatasetTable } from "@/lib/types";
import { bytes, cn, compactNumber, formatDate, number } from "@/lib/utils";

import {
  Badge,
  Card,
  CodeBlock,
  DataTable,
  Disclosure,
  Eyebrow,
  SimulatedNotice,
  Tabs,
} from "@/components/ui";

/**
 * The dataset's schema.
 *
 * Five Iceberg-style tables with their columns, partitioning and DDL. The Iceberg
 * metadata panel is the one place in the playground where numbers are *not* computed
 * from anything real, so it carries its own simulated banner rather than relying on the
 * page-level one — someone who lands on this tab from a link must still be told.
 */
export function SchemaBrowser({
  tables,
  onInsertTable,
}: {
  tables: DatasetTable[];
  onInsertTable?: (tableName: string) => void;
}) {
  const [activeName, setActiveName] = React.useState(tables[0]?.name ?? "");
  const active = tables.find((table) => table.name === activeName) ?? tables[0];

  if (!active) return null;

  return (
    <div className="grid gap-5 lg:grid-cols-[14rem_1fr] lg:gap-8">
      {/* Table list */}
      <nav aria-label="Tables" className="lg:sticky lg:top-24 lg:self-start">
        <Eyebrow as="h3">
          <span className="inline-flex items-center gap-1.5">
            <Database aria-hidden="true" className="size-3.5" />
            retail_analytics
          </span>
        </Eyebrow>
        <ul className="mt-3 space-y-1">
          {tables.map((table) => {
            const selected = table.name === active.name;
            return (
              <li key={table.name}>
                <button
                  type="button"
                  onClick={() => setActiveName(table.name)}
                  aria-current={selected ? "true" : undefined}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left",
                    "transition-colors",
                    selected
                      ? "bg-accent-50 text-ink"
                      : "text-ink-muted hover:bg-surface-sunken hover:text-ink",
                  )}
                >
                  <Table2
                    aria-hidden="true"
                    className={cn(
                      "size-3.5 shrink-0",
                      selected ? "text-accent-700 dark:text-accent-400" : "text-ink-subtle",
                    )}
                  />
                  <span className="min-w-0 flex-1 truncate font-mono text-[0.8125rem]">
                    {table.name}
                  </span>
                  <span className="shrink-0 text-[11px] tabular text-ink-subtle">
                    {compactNumber(table.row_count)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Table detail */}
      <div className="min-w-0">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="font-mono text-h3 text-ink">{active.name}</h3>
            <p className="mt-1.5 text-small text-ink-muted measure">{active.description}</p>
          </div>
          {onInsertTable && (
            <button
              type="button"
              onClick={() => onInsertTable(active.name)}
              className="shrink-0 rounded-md border border-border-strong bg-surface-raised px-2.5 py-1.5 text-small font-medium text-ink-muted transition-colors hover:border-ink-subtle hover:text-ink"
            >
              Query this table
            </button>
          )}
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Badge tone="neutral" size="sm">
            {number(active.row_count)} rows
          </Badge>
          {active.partitioned_by.map((column) => (
            <Badge key={column} tone="accent" size="sm">
              <span className="inline-flex items-center gap-1">
                <Layers3 aria-hidden="true" className="size-3" />
                partitioned by {column}
              </span>
            </Badge>
          ))}
        </div>

        <div className="mt-6">
          <Tabs
            persistKey="playground.schema"
            items={[
              { id: "columns", label: "Columns", count: active.columns.length },
              { id: "ddl", label: "DDL" },
              { id: "iceberg", label: "Iceberg metadata" },
            ]}
          >
            {(tab) => (
              <>
                {tab === "columns" && (
                  <DataTable
                    caption={`Columns of ${active.name}`}
                    rows={active.columns}
                    rowKey={(column) => column.name}
                    columns={[
                      {
                        key: "name",
                        header: "Column",
                        mobileLabel: "Column",
                        cell: (column) => (
                          <span className="inline-flex items-center gap-1.5">
                            {active.partitioned_by.includes(column.name) && (
                              <KeyRound
                                aria-label="Partition key"
                                className="size-3 text-accent-600 dark:text-accent-400"
                              />
                            )}
                            <span className="font-mono text-[0.8125rem] text-ink">
                              {column.name}
                            </span>
                          </span>
                        ),
                      },
                      {
                        key: "iceberg_type",
                        header: "Iceberg type",
                        mobileLabel: "Iceberg type",
                        cell: (column) => (
                          <span className="font-mono text-[0.8125rem] text-ink-muted">
                            {column.iceberg_type}
                          </span>
                        ),
                      },
                      {
                        key: "sql_type",
                        header: "SQL type",
                        mobileLabel: "SQL type",
                        secondary: true,
                        cell: (column) => (
                          <span className="font-mono text-[0.8125rem] text-ink-subtle">
                            {column.sql_type}
                          </span>
                        ),
                      },
                      {
                        key: "description",
                        header: "Meaning",
                        mobileLabel: "Meaning",
                        cell: (column) => (
                          <span className="text-ink-muted">{column.description}</span>
                        ),
                      },
                    ]}
                  />
                )}

                {tab === "ddl" && (
                  <div className="space-y-3">
                    <p className="text-small text-ink-muted measure">
                      How this table would be declared. Iceberg&rsquo;s partitioning is
                      hidden: queries filter on the plain column and the engine works out
                      which files to read, so a reader never has to know the layout.
                    </p>
                    <CodeBlock label={`${active.name} — DDL`}>{active.ddl}</CodeBlock>
                  </div>
                )}

                {tab === "iceberg" && <IcebergMetadata table={active} />}
              </>
            )}
          </Tabs>
        </div>
      </div>
    </div>
  );
}

function IcebergMetadata({ table }: { table: DatasetTable }) {
  const metadata = table.simulated_metadata;
  return (
    <div className="space-y-5">
      <SimulatedNotice>{metadata.notice}</SimulatedNotice>

      <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Format version", value: `v${metadata.format_version}` },
          { label: "Data files", value: number(metadata.total_data_files) },
          { label: "Delete files", value: number(metadata.total_delete_files) },
          { label: "Manifest files", value: number(metadata.manifest_files) },
          { label: "Records", value: number(metadata.total_records) },
          { label: "Estimated size", value: bytes(metadata.estimated_size_bytes) },
          {
            label: "Current snapshot",
            value: (
              <span className="font-mono text-[0.75rem]">{metadata.current_snapshot_id}</span>
            ),
          },
          { label: "Snapshots", value: number(metadata.snapshots.length) },
        ].map((entry) => (
          <div key={entry.label} className="min-w-0">
            <dt className="text-[11px] uppercase tracking-wide text-ink-subtle">
              {entry.label}
            </dt>
            <dd className="mt-0.5 text-small tabular text-ink">{entry.value}</dd>
          </div>
        ))}
      </dl>

      <div>
        <Eyebrow as="h4">Snapshot history</Eyebrow>
        <p className="mt-1.5 text-small text-ink-muted measure">
          Every write to an Iceberg table creates a snapshot rather than overwriting what
          was there. That is what makes time travel and rollback possible — and it is the
          property that distinguishes a lakehouse table from a folder of Parquet files.
        </p>
        <ol className="mt-3.5 space-y-2.5">
          {metadata.snapshots.map((snapshot, index) => (
            <li
              key={snapshot.snapshot_id}
              className="rounded-md border border-border bg-surface-raised p-3.5"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2.5">
                <span className="inline-flex items-center gap-2">
                  <Badge tone={index === 0 ? "accent" : "neutral"} size="sm">
                    {snapshot.operation}
                  </Badge>
                  {index === 0 && (
                    <span className="text-[11px] uppercase tracking-wide text-ink-subtle">
                      current
                    </span>
                  )}
                </span>
                <span className="text-small text-ink-subtle">
                  {formatDate(snapshot.committed_at)}
                </span>
              </div>
              <p className="mt-2 text-small text-ink-muted">{snapshot.summary}</p>
              <p className="mt-1.5 text-[11px] tabular text-ink-subtle">
                +{number(snapshot.added_files)} files · +{number(snapshot.added_records)}{" "}
                records · id{" "}
                <span className="font-mono">{snapshot.snapshot_id}</span>
              </p>
            </li>
          ))}
        </ol>
      </div>

      <Card tone="sunken">
        <Disclosure
          summary={
            <span className="text-small font-medium text-ink">
              What this metadata lets you do
            </span>
          }
          defaultOpen
        >
          <ul className="space-y-2">
            {metadata.capabilities_demonstrated.map((capability) => (
              <li key={capability} className="flex items-start gap-2.5">
                <span
                  aria-hidden="true"
                  className="mt-[0.4rem] size-1.5 shrink-0 rounded-full bg-accent-500"
                />
                <span className="text-small text-ink-muted">{capability}</span>
              </li>
            ))}
          </ul>
        </Disclosure>
      </Card>
    </div>
  );
}
