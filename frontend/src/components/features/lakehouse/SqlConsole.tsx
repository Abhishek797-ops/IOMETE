"use client";

import * as React from "react";

import {
  AlertCircle,
  BarChart3,
  GraduationCap,
  ListTree,
  Play,
  RotateCcw,
  Scissors,
  Table2,
  Timer,
} from "lucide-react";

import { api } from "@/lib/api";
import { useMutation, useLocalPreference } from "@/lib/hooks";
import type { PlaygroundStatus, QueryResult, SampleQuery } from "@/lib/types";
import { cn, number, sessionKey } from "@/lib/utils";

import { QueryChart } from "@/components/charts";
import {
  Badge,
  Button,
  Card,
  CodeBlock,
  DataTable,
  Disclosure,
  Eyebrow,
  EmptyState,
  FormError,
  Kbd,
  SimulatedBadge,
  SimulatedNotice,
  Tabs,
} from "@/components/ui";

const DIFFICULTY_TONE = {
  starter: "positive",
  intermediate: "caution",
  advanced: "critical",
} as const;

const STARTER_SQL = `SELECT
    region,
    COUNT(*)                     AS orders,
    ROUND(SUM(gross_amount), 2)  AS gross_revenue
FROM retail_analytics.orders
WHERE status != 'cancelled'
GROUP BY region
ORDER BY gross_revenue DESC`;

/**
 * The SQL console.
 *
 * The queries genuinely execute — against a synthetic dataset, in a read-only sandbox —
 * and the component says so in those words. That distinction is the whole point of the
 * playground: the computation is real, the data is not, and the Iceberg metadata and
 * execution plan beside it are teaching devices rather than readings from a live cluster.
 * Each of those three claims is labelled separately, because they are separately true.
 */
export function SqlConsole({
  samples,
  status,
}: {
  samples: SampleQuery[];
  status: PlaygroundStatus;
}) {
  const [sql, setSql] = useLocalPreference<string>("playground.sql", STARTER_SQL);
  const [result, setResult] = React.useState<QueryResult | null>(null);
  const [activeSample, setActiveSample] = React.useState<string | null>(null);

  const editorRef = React.useRef<HTMLTextAreaElement>(null);
  const resultRef = React.useRef<HTMLDivElement>(null);

  const run = useMutation(
    async (body: { sql?: string; sample_id?: string }) =>
      api.runQuery({ ...body, session_key: sessionKey() }),
    {
      onSuccess: (next) => {
        setResult(next);
        // Bring the result into view on a phone, where the editor fills the screen.
        requestAnimationFrame(() => {
          resultRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
        });
      },
    },
  );

  const runSql = () => {
    setActiveSample(null);
    void run.run({ sql });
  };

  const runSample = (sample: SampleQuery) => {
    setActiveSample(sample.id);
    setSql(sample.sql);
    void run.run({ sample_id: sample.id });
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      runSql();
    }
  };

  const sample = activeSample ? samples.find((item) => item.id === activeSample) : null;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_19rem] lg:gap-8">
      {/* ------------------------------------------------------------- Editor */}
      <div className="min-w-0 space-y-5">
        <Card className="overflow-hidden p-0">
          <div className="flex flex-wrap items-center gap-2.5 border-b border-border bg-surface-sunken px-4 py-2.5">
            <Eyebrow as="h3">Query editor</Eyebrow>
            <Badge tone="neutral" size="sm">
              SELECT only
            </Badge>
            <span className="ml-auto text-[11px] text-ink-subtle">
              <Kbd>⌘</Kbd> <Kbd>↵</Kbd> to run
            </span>
          </div>

          <label htmlFor="playground-sql" className="sr-only">
            SQL query
          </label>
          <textarea
            id="playground-sql"
            ref={editorRef}
            value={sql}
            onChange={(event) => setSql(event.target.value)}
            onKeyDown={onKeyDown}
            spellCheck={false}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            rows={12}
            className={cn(
              "block w-full resize-y bg-surface-raised px-4 py-3.5",
              "font-mono text-[0.8125rem] leading-relaxed text-ink",
              "outline-none placeholder:text-ink-subtle",
              "focus-visible:bg-surface-raised",
            )}
            placeholder="SELECT * FROM retail_analytics.orders LIMIT 10"
          />

          <div className="flex flex-wrap items-center gap-2.5 border-t border-border bg-surface-sunken px-4 py-3">
            <Button
              variant="primary"
              onClick={runSql}
              loading={run.pending}
              disabled={sql.trim().length === 0}
              icon={<Play />}
            >
              Run query
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setSql(STARTER_SQL);
                setActiveSample(null);
                editorRef.current?.focus();
              }}
              icon={<RotateCcw />}
            >
              Reset
            </Button>
            <span className="ml-auto text-[11px] text-ink-subtle">
              Max {number(status.limits.max_rows)} rows ·{" "}
              {status.limits.statement_timeout_seconds}s timeout · read-only
            </span>
          </div>
        </Card>

        <FormError error={run.error} />

        {sample && (
          <Card tone="sunken">
            <div className="flex items-start gap-2.5">
              <GraduationCap
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 text-accent-700 dark:text-accent-400"
              />
              <div className="min-w-0">
                <h4 className="text-small font-medium text-ink">
                  What this query teaches
                </h4>
                <p className="mt-1 text-small text-ink-muted measure">{sample.teaches}</p>
              </div>
            </div>
          </Card>
        )}

        <div ref={resultRef}>
          {result ? (
            <ResultPanel result={result} />
          ) : (
            <EmptyState
              icon={<Table2 />}
              title="No results yet"
              description="Run the query above, or pick one of the guided examples to see what a lakehouse query looks like and what it teaches."
            />
          )}
        </div>
      </div>

      {/* ------------------------------------------------------------ Samples */}
      <aside className="min-w-0 lg:sticky lg:top-24 lg:self-start">
        <Eyebrow as="h3">Guided queries</Eyebrow>
        <p className="mt-1.5 text-small text-ink-muted">
          Each one demonstrates something specific about how a lakehouse works, not just
          what the data says.
        </p>
        <ul className="mt-3.5 space-y-2">
          {samples.map((item) => {
            const selected = item.id === activeSample;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => runSample(item)}
                  aria-current={selected ? "true" : undefined}
                  className={cn(
                    "w-full rounded-lg border p-3 text-left transition-colors",
                    selected
                      ? "border-accent-400 bg-accent-50"
                      : "border-border bg-surface-raised hover:border-border-strong",
                  )}
                >
                  <div className="flex items-start justify-between gap-2.5">
                    <span className="text-small font-medium text-ink">{item.title}</span>
                    <Badge tone={DIFFICULTY_TONE[item.difficulty]} size="sm">
                      {item.difficulty}
                    </Badge>
                  </div>
                  <p className="mt-1.5 text-[11px] leading-snug text-ink-muted">
                    {item.teaches}
                  </p>
                </button>
              </li>
            );
          })}
        </ul>
      </aside>
    </div>
  );
}

/**
 * A query result: the table, the chart, and the simulated plan.
 *
 * The table comes first and is always complete. The chart is secondary and will refuse to
 * render if the columns do not match its hint — a chart of the wrong thing is worse than
 * no chart, and the numbers are never gated behind one.
 */
function ResultPanel({ result }: { result: QueryResult }) {
  const columns = React.useMemo(
    () =>
      result.columns.map((column, index) => ({
        key: column,
        header: column,
        mobileLabel: column,
        numeric: result.rows.some((row) => typeof row[index] === "number"),
        align: (result.rows.some((row) => typeof row[index] === "number")
          ? "right"
          : "left") as "left" | "right",
        cell: (row: (string | number | null)[]) => {
          const value = row[index];
          if (value === null || value === undefined) {
            return <span className="text-ink-subtle">null</span>;
          }
          return typeof value === "number" ? number(value) : String(value);
        },
      })),
    [result.columns, result.rows],
  );

  const hasChart = Boolean(result.sample?.chart);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <Eyebrow as="h3">Result</Eyebrow>
        <Badge tone="neutral" size="sm">
          {number(result.row_count)} row{result.row_count === 1 ? "" : "s"}
        </Badge>
        <Badge tone="neutral" size="sm">
          <span className="inline-flex items-center gap-1">
            <Timer aria-hidden="true" className="size-3" />
            {result.duration_ms} ms
          </span>
        </Badge>
        {result.scanned_tables.length > 0 && (
          <Badge tone="neutral" size="sm">
            scanned {result.scanned_tables.join(", ")}
          </Badge>
        )}
        {result.is_simulated && <SimulatedBadge />}
      </div>

      {result.truncated && (
        <div className="flex items-start gap-2.5 rounded-md border border-caution/30 bg-caution-soft px-3.5 py-2.5">
          <Scissors aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-caution" />
          <p className="text-small text-ink-muted">
            This result was truncated to the row limit. The numbers shown are a prefix of
            the answer, not the whole of it — add a <code className="font-mono">LIMIT</code>{" "}
            or an aggregation to see a complete result.
          </p>
        </div>
      )}

      {result.notice && (
        <div className="flex items-start gap-2.5 rounded-md border border-info/25 bg-info-soft px-3.5 py-2.5">
          <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-info" />
          <p className="text-small text-ink-muted">{result.notice}</p>
        </div>
      )}

      <Tabs
        persistKey="playground.result"
        items={[
          { id: "table", label: "Table", icon: <Table2 />, count: result.row_count },
          ...(hasChart ? [{ id: "chart", label: "Chart", icon: <BarChart3 /> }] : []),
          {
            id: "plan",
            label: "Execution plan",
            icon: <ListTree />,
            count: result.execution_plan.length,
          },
        ]}
      >
        {(tab) => (
          <>
            {tab === "table" && (
              <DataTable
                caption="Query result"
                layout="scroll"
                rows={result.rows}
                rowKey={(row) => row.map((value) => String(value)).join("|")}
                columns={columns}
                emptyMessage={
                  <p className="text-small text-ink-subtle">
                    The query ran and matched no rows.
                  </p>
                }
              />
            )}

            {tab === "chart" && result.sample?.chart && (
              <QueryChart
                columns={result.columns}
                rows={result.rows}
                chart={result.sample.chart}
                title={result.sample.title}
                note="Plotted from the result above. Synthetic data."
              />
            )}

            {tab === "plan" && (
              <div className="space-y-4">
                <SimulatedNotice>{result.execution_plan_notice}</SimulatedNotice>
                <ol className="space-y-2.5">
                  {result.execution_plan.map((step) => (
                    <li
                      key={step.step}
                      className="rounded-md border border-border bg-surface-raised p-3.5"
                    >
                      <div className="flex flex-wrap items-center gap-2.5">
                        <span
                          aria-hidden="true"
                          className="grid size-5 shrink-0 place-items-center rounded-full bg-surface-inset text-[11px] font-semibold text-ink-muted"
                        >
                          {step.step}
                        </span>
                        <span className="font-mono text-[0.8125rem] font-medium text-ink">
                          {step.operator}
                        </span>
                        {step.partition_pruning && (
                          <Badge tone="accent" size="sm">
                            partition pruning
                          </Badge>
                        )}
                      </div>
                      <p className="mt-2 font-mono text-[0.75rem] text-ink-subtle">
                        {step.detail}
                      </p>
                      <p className="mt-2 text-small text-ink-muted">{step.note}</p>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </>
        )}
      </Tabs>

      <Disclosure
        summary={
          <span className="text-small text-ink-muted">The SQL that produced this</span>
        }
      >
        <CodeBlock label="Executed statement">{result.sql}</CodeBlock>
        <p className="mt-2.5 text-[11px] text-ink-subtle">{result.simulation_notice}</p>
      </Disclosure>
    </div>
  );
}
