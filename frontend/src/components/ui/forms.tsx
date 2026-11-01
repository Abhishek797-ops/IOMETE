"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Form primitives.
 *
 * Every control wires its own label, description and error through `aria-describedby` and
 * `aria-invalid`. Doing that once here is the difference between a form that a screen
 * reader can actually be used with and one where the error text is invisible — and it
 * stops each page re-deriving the plumbing.
 */

const CONTROL_BASE =
  "w-full rounded-md border bg-surface-raised text-body text-ink " +
  "placeholder:text-ink-subtle transition-[border-color,box-shadow] duration-150 " +
  "disabled:cursor-not-allowed disabled:bg-surface-inset disabled:text-ink-subtle " +
  "aria-[invalid=true]:border-critical aria-[invalid=true]:ring-1 " +
  "aria-[invalid=true]:ring-critical/30";

const CONTROL_SIZE = "min-h-10 px-3 py-2";

function useFieldIds(id: string | undefined, hasDescription: boolean, hasError: boolean) {
  const generated = React.useId();
  const fieldId = id ?? generated;
  const descriptionId = hasDescription ? `${fieldId}-description` : undefined;
  const errorId = hasError ? `${fieldId}-error` : undefined;
  const describedBy = [descriptionId, errorId].filter(Boolean).join(" ") || undefined;
  return { fieldId, descriptionId, errorId, describedBy };
}

export function Label({
  htmlFor,
  children,
  required,
  className,
}: {
  htmlFor?: string;
  children: React.ReactNode;
  required?: boolean;
  className?: string;
}) {
  return (
    <label htmlFor={htmlFor} className={cn("block text-small font-medium text-ink", className)}>
      {children}
      {required && (
        <>
          <span aria-hidden="true" className="ml-1 text-critical">
            *
          </span>
          <span className="sr-only"> (required)</span>
        </>
      )}
    </label>
  );
}

export function FieldDescription({
  id,
  children,
  className,
}: {
  id?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <p id={id} className={cn("text-small text-ink-subtle measure", className)}>
      {children}
    </p>
  );
}

export function FieldError({
  id,
  children,
  className,
}: {
  id?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    // `role="alert"` so the message is announced when it appears after a failed submit.
    <p id={id} role="alert" className={cn("text-small font-medium text-critical", className)}>
      {children}
    </p>
  );
}

interface FieldShellProps {
  label?: React.ReactNode;
  description?: React.ReactNode;
  error?: string | null;
  required?: boolean;
  hint?: React.ReactNode;
  className?: string;
}

export interface InputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size">,
    FieldShellProps {}

export function Input({
  label,
  description,
  error,
  required,
  hint,
  className,
  id,
  ...rest
}: InputProps) {
  const { fieldId, descriptionId, errorId, describedBy } = useFieldIds(
    id,
    Boolean(description),
    Boolean(error),
  );
  return (
    <div className={cn("space-y-1.5", className)}>
      {label && (
        <div className="flex items-baseline justify-between gap-3">
          <Label htmlFor={fieldId} required={required}>
            {label}
          </Label>
          {hint && <span className="text-small text-ink-subtle">{hint}</span>}
        </div>
      )}
      {description && (
        <FieldDescription id={descriptionId}>{description}</FieldDescription>
      )}
      <input
        id={fieldId}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn(CONTROL_BASE, CONTROL_SIZE, "border-border-strong")}
        {...rest}
      />
      {error && <FieldError id={errorId}>{error}</FieldError>}
    </div>
  );
}

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement>,
    FieldShellProps {
  /** Shows a live character count. Useful where the backend enforces a minimum length. */
  showCount?: boolean;
  minLengthHint?: number;
}

export function Textarea({
  label,
  description,
  error,
  required,
  hint,
  className,
  id,
  showCount,
  minLengthHint,
  value,
  rows = 5,
  ...rest
}: TextareaProps) {
  const { fieldId, descriptionId, errorId, describedBy } = useFieldIds(
    id,
    Boolean(description),
    Boolean(error),
  );
  const length = typeof value === "string" ? value.length : 0;
  const belowMinimum = minLengthHint !== undefined && length > 0 && length < minLengthHint;

  return (
    <div className={cn("space-y-1.5", className)}>
      {label && (
        <div className="flex items-baseline justify-between gap-3">
          <Label htmlFor={fieldId} required={required}>
            {label}
          </Label>
          {hint && <span className="text-small text-ink-subtle">{hint}</span>}
        </div>
      )}
      {description && (
        <FieldDescription id={descriptionId}>{description}</FieldDescription>
      )}
      <textarea
        id={fieldId}
        rows={rows}
        required={required}
        value={value}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn(CONTROL_BASE, "border-border-strong px-3 py-2 leading-relaxed")}
        {...rest}
      />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">{error && <FieldError id={errorId}>{error}</FieldError>}</div>
        {showCount && (
          <span
            className={cn(
              "shrink-0 text-small tabular",
              belowMinimum ? "text-caution" : "text-ink-subtle",
            )}
          >
            {length}
            {minLengthHint !== undefined && ` / ${minLengthHint} min`}
          </span>
        )}
      </div>
    </div>
  );
}

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement>,
    FieldShellProps {
  options: SelectOption[];
  placeholder?: string;
}

export function Select({
  label,
  description,
  error,
  required,
  hint,
  className,
  id,
  options,
  placeholder,
  ...rest
}: SelectProps) {
  const { fieldId, descriptionId, errorId, describedBy } = useFieldIds(
    id,
    Boolean(description),
    Boolean(error),
  );
  return (
    <div className={cn("space-y-1.5", className)}>
      {label && (
        <div className="flex items-baseline justify-between gap-3">
          <Label htmlFor={fieldId} required={required}>
            {label}
          </Label>
          {hint && <span className="text-small text-ink-subtle">{hint}</span>}
        </div>
      )}
      {description && (
        <FieldDescription id={descriptionId}>{description}</FieldDescription>
      )}
      <div className="relative">
        <select
          id={fieldId}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={cn(
            CONTROL_BASE,
            CONTROL_SIZE,
            "appearance-none border-border-strong pr-9",
          )}
          {...rest}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options.map((option) => (
            <option key={option.value} value={option.value} disabled={option.disabled}>
              {option.label}
            </option>
          ))}
        </select>
        <svg
          aria-hidden="true"
          viewBox="0 0 12 12"
          className="pointer-events-none absolute right-3 top-1/2 size-3 -translate-y-1/2 text-ink-subtle"
        >
          <path
            d="M2.5 4.5 6 8l3.5-3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
      {error && <FieldError id={errorId}>{error}</FieldError>}
    </div>
  );
}

export function Checkbox({
  label,
  description,
  error,
  id,
  className,
  ...rest
}: Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> & {
  label: React.ReactNode;
  description?: React.ReactNode;
  error?: string | null;
}) {
  const { fieldId, descriptionId, errorId, describedBy } = useFieldIds(
    id,
    Boolean(description),
    Boolean(error),
  );
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-start gap-2.5">
        <input
          id={fieldId}
          type="checkbox"
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={cn(
            "mt-0.5 size-4 shrink-0 cursor-pointer rounded border-border-strong",
            "text-accent-600 accent-accent-600",
            "aria-[invalid=true]:border-critical",
          )}
          {...rest}
        />
        <div className="min-w-0">
          <label htmlFor={fieldId} className="cursor-pointer text-small text-ink">
            {label}
          </label>
          {description && (
            <FieldDescription id={descriptionId} className="mt-1">
              {description}
            </FieldDescription>
          )}
        </div>
      </div>
      {error && <FieldError id={errorId}>{error}</FieldError>}
    </div>
  );
}

/**
 * A radio group rendered as selectable cards.
 *
 * Used throughout the Fit Finder: when each option needs a sentence of explanation, a
 * native select hides the very information the person needs to choose well.
 */
export function RadioCardGroup<T extends string>({
  name,
  label,
  description,
  options,
  value,
  onChange,
  error,
  required,
  columns = 1,
  className,
}: {
  name: string;
  label: React.ReactNode;
  description?: React.ReactNode;
  options: { value: T; label: string; hint?: string; icon?: React.ReactNode }[];
  value: T | "";
  onChange: (value: T) => void;
  error?: string | null;
  required?: boolean;
  columns?: 1 | 2 | 3;
  className?: string;
}) {
  const groupId = React.useId();
  const descriptionId = description ? `${groupId}-description` : undefined;
  const errorId = error ? `${groupId}-error` : undefined;

  return (
    <fieldset
      className={cn("space-y-3", className)}
      aria-describedby={[descriptionId, errorId].filter(Boolean).join(" ") || undefined}
      aria-invalid={error ? true : undefined}
    >
      <legend className="text-small font-medium text-ink">
        {label}
        {required && (
          <>
            <span aria-hidden="true" className="ml-1 text-critical">
              *
            </span>
            <span className="sr-only"> (required)</span>
          </>
        )}
      </legend>
      {description && (
        <FieldDescription id={descriptionId}>{description}</FieldDescription>
      )}
      <div
        className={cn(
          "grid gap-2.5",
          columns === 2 && "sm:grid-cols-2",
          columns === 3 && "sm:grid-cols-2 lg:grid-cols-3",
        )}
      >
        {options.map((option) => {
          const selected = value === option.value;
          return (
            <label
              key={option.value}
              className={cn(
                "group relative flex cursor-pointer gap-3 rounded-lg border p-3.5",
                "transition-[border-color,background-color,box-shadow] duration-150",
                selected
                  ? "border-accent-500 bg-accent-50 shadow-subtle ring-1 ring-accent-500/30"
                  : "border-border bg-surface-raised hover:border-border-strong hover:bg-surface-sunken",
                "has-[:focus-visible]:outline has-[:focus-visible]:outline-2",
                "has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent-500",
              )}
            >
              <input
                type="radio"
                name={name}
                value={option.value}
                checked={selected}
                required={required}
                onChange={() => onChange(option.value)}
                className="mt-0.5 size-4 shrink-0 cursor-pointer accent-accent-600"
              />
              <span className="min-w-0">
                <span className="flex items-center gap-2 text-small font-medium text-ink">
                  {option.icon && (
                    <span className="text-ink-subtle [&>svg]:size-4">{option.icon}</span>
                  )}
                  {option.label}
                </span>
                {option.hint && (
                  <span className="mt-1 block text-small text-ink-muted">{option.hint}</span>
                )}
              </span>
            </label>
          );
        })}
      </div>
      {error && <FieldError id={errorId}>{error}</FieldError>}
    </fieldset>
  );
}

/** Multi-select as toggleable chips. For "which of these apply?" questions. */
export function ChipMultiSelect<T extends string>({
  label,
  description,
  options,
  values,
  onChange,
  error,
  className,
}: {
  label: React.ReactNode;
  description?: React.ReactNode;
  options: { value: T; label: string }[];
  values: T[];
  onChange: (values: T[]) => void;
  error?: string | null;
  className?: string;
}) {
  const groupId = React.useId();
  const descriptionId = description ? `${groupId}-description` : undefined;

  const toggle = (option: T) => {
    onChange(values.includes(option) ? values.filter((v) => v !== option) : [...values, option]);
  };

  return (
    <fieldset className={cn("space-y-3", className)} aria-describedby={descriptionId}>
      <legend className="text-small font-medium text-ink">{label}</legend>
      {description && (
        <FieldDescription id={descriptionId}>{description}</FieldDescription>
      )}
      <div className="flex flex-wrap gap-2">
        {options.map((option) => {
          const selected = values.includes(option.value);
          return (
            <button
              key={option.value}
              type="button"
              onClick={() => toggle(option.value)}
              aria-pressed={selected}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5",
                "text-small font-medium transition-colors duration-150",
                selected
                  ? "border-accent-500 bg-accent-50 text-accent-800 dark:text-accent-200"
                  : "border-border-strong bg-surface-raised text-ink-muted hover:border-ink-subtle hover:text-ink",
              )}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "grid size-3.5 place-items-center rounded-[3px] border transition-colors",
                  selected
                    ? "border-accent-600 bg-accent-600 text-white"
                    : "border-border-strong",
                )}
              >
                {selected && (
                  <svg viewBox="0 0 10 10" className="size-2.5" fill="none">
                    <path
                      d="M1.5 5.2 3.7 7.4 8.5 2.6"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                )}
              </span>
              {option.label}
            </button>
          );
        })}
      </div>
      {error && <FieldError>{error}</FieldError>}
    </fieldset>
  );
}

/**
 * A free-text list builder. Used for "which systems do you run?" where the answer cannot
 * be enumerated in advance and a text box would produce unparseable prose.
 */
export function TagInput({
  label,
  description,
  placeholder,
  values,
  onChange,
  suggestions = [],
  className,
}: {
  label: React.ReactNode;
  description?: React.ReactNode;
  placeholder?: string;
  values: string[];
  onChange: (values: string[]) => void;
  suggestions?: string[];
  className?: string;
}) {
  const [draft, setDraft] = React.useState("");
  const inputId = React.useId();
  const descriptionId = description ? `${inputId}-description` : undefined;

  const add = (raw: string) => {
    const value = raw.trim();
    if (!value || values.includes(value)) return;
    onChange([...values, value]);
    setDraft("");
  };

  const remove = (value: string) => onChange(values.filter((item) => item !== value));

  const available = suggestions.filter((suggestion) => !values.includes(suggestion));

  return (
    <div className={cn("space-y-1.5", className)}>
      <Label htmlFor={inputId}>{label}</Label>
      {description && (
        <FieldDescription id={descriptionId}>{description}</FieldDescription>
      )}

      {values.length > 0 && (
        <ul className="flex flex-wrap gap-2 pt-1" aria-label={`Selected: ${values.join(", ")}`}>
          {values.map((value) => (
            <li key={value}>
              <span
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border border-accent-200",
                  "bg-accent-50 py-1 pl-3 pr-1 text-small text-accent-800 dark:text-accent-200",
                )}
              >
                {value}
                <button
                  type="button"
                  onClick={() => remove(value)}
                  aria-label={`Remove ${value}`}
                  className={cn(
                    "grid size-5 place-items-center rounded-full text-accent-700",
                    "transition-colors hover:bg-accent-200 dark:text-accent-300",
                  )}
                >
                  <svg viewBox="0 0 10 10" className="size-2.5" fill="none" aria-hidden="true">
                    <path
                      d="M1.5 1.5l7 7m0-7l-7 7"
                      stroke="currentColor"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                    />
                  </svg>
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-2">
        <input
          id={inputId}
          value={draft}
          placeholder={placeholder}
          aria-describedby={descriptionId}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === ",") {
              event.preventDefault();
              add(draft);
            } else if (event.key === "Backspace" && !draft && values.length > 0) {
              remove(values[values.length - 1]!);
            }
          }}
          className={cn(CONTROL_BASE, CONTROL_SIZE, "border-border-strong")}
        />
        <button
          type="button"
          onClick={() => add(draft)}
          disabled={!draft.trim()}
          className={cn(
            "shrink-0 rounded-md border border-border-strong bg-surface-raised px-3",
            "text-small font-medium text-ink transition-colors hover:bg-surface-sunken",
            "disabled:opacity-45",
          )}
        >
          Add
        </button>
      </div>

      {available.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 pt-1">
          <span className="text-small text-ink-subtle">Common:</span>
          {available.slice(0, 8).map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => add(suggestion)}
              className={cn(
                "rounded-full border border-dashed border-border-strong px-2.5 py-0.5",
                "text-small text-ink-muted transition-colors hover:border-accent-400",
                "hover:bg-accent-50 hover:text-accent-800 dark:hover:text-accent-200",
              )}
            >
              + {suggestion}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
