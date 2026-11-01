"use client";

import * as React from "react";
import { createPortal } from "react-dom";

import { AlertTriangle, Check, Info, X } from "lucide-react";

import {
  useEscapeKey,
  useFocusTrap,
  useIsClient,
  useOutsideClick,
  usePrefersReducedMotion,
  useScrollLock,
} from "@/lib/hooks";
import { cn } from "@/lib/utils";

import { Button, IconButton } from "./primitives";

// =====================================================================================
// Dialog
// =====================================================================================

/**
 * A modal dialog.
 *
 * Hand-built rather than pulled from a library because the behaviour that matters is
 * small and specific: focus trapped inside while open, focus returned to the trigger on
 * close, Escape closes, body scroll locked, and `aria-modal` with a labelled title. Those
 * five things are what separate a dialog from a div that looks like one.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
  /** Set when the dialog confirms something consequential. Tints the header. */
  tone = "default",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  tone?: "default" | "danger" | "caution";
}) {
  // `useIsClient` rather than a mount effect: the portal target does not exist during
  // server rendering, and this resolves in one render instead of two.
  const isClient = useIsClient();
  const containerRef = useFocusTrap<HTMLDivElement>(open);
  const reduceMotion = usePrefersReducedMotion();
  const titleId = React.useId();
  const descriptionId = React.useId();

  useEscapeKey(onClose, open);
  useScrollLock(open);

  if (!isClient || !open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-6">
      <div
        aria-hidden="true"
        onClick={onClose}
        className={cn(
          "absolute inset-0 bg-graphite-950/55 backdrop-blur-[2px]",
          !reduceMotion && "animate-in",
        )}
      />
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        className={cn(
          "relative z-10 flex max-h-[92dvh] w-full flex-col overflow-hidden",
          "rounded-t-xl border border-border bg-surface-raised shadow-float",
          "sm:rounded-xl",
          size === "sm" && "sm:max-w-md",
          size === "md" && "sm:max-w-xl",
          size === "lg" && "sm:max-w-3xl",
          size === "xl" && "sm:max-w-5xl",
        )}
      >
        <header
          className={cn(
            "flex items-start justify-between gap-4 border-b border-border px-5 py-4",
            tone === "danger" && "bg-critical-soft",
            tone === "caution" && "bg-caution-soft",
          )}
        >
          <div className="min-w-0">
            <h2 id={titleId} className="flex items-center gap-2 text-h3 text-ink">
              {tone === "danger" && (
                <AlertTriangle aria-hidden="true" className="size-4 shrink-0 text-critical" />
              )}
              {tone === "caution" && (
                <AlertTriangle aria-hidden="true" className="size-4 shrink-0 text-caution" />
              )}
              {title}
            </h2>
            {description && (
              <p id={descriptionId} className="mt-1.5 text-small text-ink-muted">
                {description}
              </p>
            )}
          </div>
          <IconButton label="Close" size="sm" onClick={onClose} className="shrink-0">
            <X />
          </IconButton>
        </header>

        {children && <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">{children}</div>}

        {footer && (
          <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-border bg-surface-sunken px-5 py-3.5">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}

/**
 * A confirmation dialog for a consequential action.
 *
 * Used for the Resolution Replay change-step gate, where it also renders the step's blast
 * radius. Requiring a deliberate second click on an action that can restart a production
 * cluster is the point, not friction for its own sake.
 */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "caution",
  pending,
  children,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "caution" | "default";
  pending?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      tone={tone}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={pending}>
            {cancelLabel}
          </Button>
          <Button
            variant={tone === "danger" ? "danger" : "primary"}
            onClick={onConfirm}
            loading={pending}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}

// =====================================================================================
// Toast
// =====================================================================================

interface Toast {
  id: number;
  tone: "success" | "error" | "info";
  title: string;
  description?: string;
}

interface ToastContextValue {
  show: (toast: Omit<Toast, "id">) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

/**
 * Toast notifications.
 *
 * Every mutation in COMPASS produces visible feedback; this is the fallback for actions
 * whose result is not otherwise obvious on screen. The region is `aria-live="polite"` so
 * a screen reader is told what happened — a toast nobody can perceive is not feedback.
 */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const nextId = React.useRef(0);

  const dismiss = React.useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const show = React.useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = (nextId.current += 1);
      setToasts((current) => [...current, { ...toast, id }]);
      // Errors linger: they usually carry something the user has to read.
      window.setTimeout(() => dismiss(id), toast.tone === "error" ? 9000 : 5000);
    },
    [dismiss],
  );

  const value = React.useMemo<ToastContextValue>(
    () => ({
      show,
      success: (title, description) => show({ tone: "success", title, description }),
      error: (title, description) => show({ tone: "error", title, description }),
      info: (title, description) => show({ tone: "info", title, description }),
    }),
    [show],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        role="region"
        aria-live="polite"
        aria-label="Notifications"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:items-end"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              "pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-lg border",
              "bg-surface-raised px-3.5 py-3 shadow-float",
              toast.tone === "success" && "border-positive/30",
              toast.tone === "error" && "border-critical/30",
              toast.tone === "info" && "border-border-strong",
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "mt-0.5 grid size-5 shrink-0 place-items-center rounded-full [&>svg]:size-3",
                toast.tone === "success" && "bg-positive-soft text-positive",
                toast.tone === "error" && "bg-critical-soft text-critical",
                toast.tone === "info" && "bg-info-soft text-info",
              )}
            >
              {toast.tone === "success" ? (
                <Check />
              ) : toast.tone === "error" ? (
                <AlertTriangle />
              ) : (
                <Info />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-small font-medium text-ink">{toast.title}</p>
              {toast.description && (
                <p className="mt-0.5 text-small text-ink-muted">{toast.description}</p>
              )}
            </div>
            <IconButton
              label="Dismiss"
              size="sm"
              onClick={() => dismiss(toast.id)}
              className="-mr-1 -mt-1 shrink-0"
            >
              <X />
            </IconButton>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = React.useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>.");
  return context;
}

// =====================================================================================
// Tooltip / Popover
// =====================================================================================

/**
 * A hover and focus tooltip.
 *
 * Opens on focus as well as hover, and the content is also exposed through
 * `aria-describedby` — a tooltip that only appears on mouse hover is invisible to a
 * keyboard or screen-reader user, which is the usual way these are got wrong.
 */
export function Tooltip({
  content,
  children,
  side = "top",
  className,
}: {
  content: React.ReactNode;
  children: React.ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const id = React.useId();

  return (
    <span
      className={cn("relative inline-flex", className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <span aria-describedby={id}>{children}</span>
      <span
        id={id}
        role="tooltip"
        className={cn(
          "pointer-events-none absolute z-40 w-max max-w-[16rem] rounded-md border",
          "border-graphite-700 bg-graphite-900 px-2.5 py-1.5 text-[11px] leading-snug",
          "text-ink-inverse shadow-float transition-opacity duration-150",
          open ? "opacity-100" : "opacity-0",
          side === "top" && "bottom-full left-1/2 mb-2 -translate-x-1/2",
          side === "bottom" && "left-1/2 top-full mt-2 -translate-x-1/2",
          side === "left" && "right-full top-1/2 mr-2 -translate-y-1/2",
          side === "right" && "left-full top-1/2 ml-2 -translate-y-1/2",
        )}
      >
        {content}
      </span>
    </span>
  );
}

/**
 * An inline explainer, triggered by a small question mark.
 *
 * Used for the three confidence scores and the metric methodology — places where a
 * sentence of explanation prevents a misreading, but where putting that sentence inline
 * every time would bury the data.
 */
export function InfoHint({
  label,
  children,
  className,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const panelId = React.useId();
  const containerRef = useOutsideClick<HTMLSpanElement>(open, () => setOpen(false));

  useEscapeKey(() => setOpen(false), open);

  return (
    <span ref={containerRef} className={cn("relative inline-flex", className)}>
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className={cn(
          "grid size-4 place-items-center rounded-full border border-border-strong",
          "text-[9px] font-bold leading-none text-ink-subtle transition-colors",
          "hover:border-ink-subtle hover:text-ink",
        )}
      >
        ?
      </button>
      {open && (
        <span
          id={panelId}
          role="note"
          className={cn(
            "absolute left-1/2 top-full z-40 mt-2 w-64 -translate-x-1/2 rounded-md border",
            "border-border bg-surface-raised p-3 text-small leading-snug text-ink-muted",
            "shadow-float",
          )}
        >
          {children}
        </span>
      )}
    </span>
  );
}

/**
 * A collapsible disclosure.
 *
 * Native `<details>` so it works without JavaScript and is keyboard-operable for free.
 * Used for retrieval internals, execution plans and long citation lists — information
 * that should be available but not shouted.
 */
export function Disclosure({
  summary,
  children,
  defaultOpen,
  className,
  count,
}: {
  summary: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
  className?: string;
  count?: number;
}) {
  return (
    <details
      open={defaultOpen}
      className={cn(
        "group rounded-md border border-border bg-surface-raised",
        className,
      )}
    >
      <summary
        className={cn(
          "flex cursor-pointer list-none items-center gap-2 rounded-md px-3.5 py-2.5",
          "text-small font-medium text-ink-muted transition-colors hover:text-ink",
          "focus-visible:outline-2 [&::-webkit-details-marker]:hidden",
        )}
      >
        <svg
          aria-hidden="true"
          viewBox="0 0 12 12"
          className="size-3 shrink-0 transition-transform duration-200 group-open:rotate-90"
        >
          <path
            d="M4.5 2.5 8 6l-3.5 3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span className="min-w-0 flex-1">{summary}</span>
        {count !== undefined && (
          <span className="shrink-0 rounded-full bg-surface-inset px-1.5 py-0.5 text-[11px] tabular text-ink-subtle">
            {count}
          </span>
        )}
      </summary>
      <div className="border-t border-border px-3.5 py-3.5">{children}</div>
    </details>
  );
}
