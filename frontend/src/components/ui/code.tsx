"use client";

import * as React from "react";

import { Check, Copy, Terminal } from "lucide-react";

import { cn } from "@/lib/utils";

import { useToast } from "./overlays";

/**
 * A read-only code block with a copy button.
 *
 * Deliberately not an editor and deliberately not executable. COMPASS shows diagnostic
 * commands for a person to run themselves — never runs them — so the affordance offered
 * here is "copy", and the component has no path to execution at all.
 *
 * `label` names what the block is (a shell, a SQL statement, a file). `caution` marks a
 * command whose effect is not read-only, which the playbook renderer uses so that a
 * destructive step cannot be mistaken for an inspection step.
 */
export function CodeBlock({
  children,
  label,
  caution,
  className,
  maxHeight,
}: {
  children: string;
  label?: React.ReactNode;
  caution?: React.ReactNode;
  className?: string;
  /** A CSS length. Beyond it the block scrolls rather than pushing the page down. */
  maxHeight?: string;
}) {
  const [copied, setCopied] = React.useState(false);
  const toast = useToast();
  const timer = React.useRef<number | null>(null);

  React.useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(children);
      setCopied(true);
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(
        "Could not copy",
        "Your browser blocked clipboard access — select the text and copy it manually.",
      );
    }
  };

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border",
        caution ? "border-caution/40" : "border-border",
        className,
      )}
    >
      <div
        className={cn(
          "flex items-center gap-2 border-b px-3 py-1.5",
          caution
            ? "border-caution/30 bg-caution-soft"
            : "border-border bg-surface-sunken",
        )}
      >
        <Terminal aria-hidden="true" className="size-3.5 shrink-0 text-ink-subtle" />
        <span className="min-w-0 flex-1 truncate text-[11px] uppercase tracking-wide text-ink-subtle">
          {label ?? "Code"}
        </span>
        <button
          type="button"
          onClick={() => void copy()}
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 rounded px-1.5 py-1",
            "text-[11px] font-medium text-ink-muted transition-colors",
            "hover:bg-surface-inset hover:text-ink",
          )}
        >
          {copied ? (
            <>
              <Check aria-hidden="true" className="size-3 text-positive" />
              Copied
            </>
          ) : (
            <>
              <Copy aria-hidden="true" className="size-3" />
              Copy
            </>
          )}
          <span className="sr-only"> to clipboard</span>
        </button>
      </div>

      {caution && (
        <p className="border-b border-caution/30 bg-caution-soft px-3 py-2 text-small text-ink-muted">
          {caution}
        </p>
      )}

      <pre
        tabIndex={0}
        className="overflow-auto bg-surface-raised px-3.5 py-3 font-mono text-[0.8125rem] leading-relaxed text-ink"
        style={maxHeight ? { maxHeight } : undefined}
      >
        <code>{children}</code>
      </pre>
    </div>
  );
}
