import { cn } from "@/lib/utils";

/**
 * The COMPASS mark.
 *
 * A compass needle inside a ring, drawn as inline SVG rather than shipped as an image:
 * it inherits `currentColor`, so it works on the warm public surface and the graphite
 * operator chrome without a second asset, and it stays crisp at any size.
 *
 * The needle points north-east rather than north — a compass under use rather than a
 * decorative icon, which is the right note for a product about finding your way through
 * an investigation.
 */
export function CompassMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 28 28"
      fill="none"
      aria-hidden="true"
      className={cn("size-7", className)}
    >
      <circle cx="14" cy="14" r="12.25" stroke="currentColor" strokeWidth="1.5" opacity="0.28" />
      <circle cx="14" cy="14" r="9" stroke="currentColor" strokeWidth="1" opacity="0.16" />
      {/* Cardinal ticks */}
      <path
        d="M14 1.5v2.4M14 24.1v2.4M1.5 14h2.4M24.1 14h2.4"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        opacity="0.45"
      />
      {/* The needle: filled half points the bearing, hollow half is the tail. */}
      <path d="M19.4 8.6 15.1 15.1 8.6 19.4 12.9 12.9z" fill="currentColor" />
      <path
        d="M8.6 19.4 12.9 12.9 19.4 8.6 15.1 15.1z"
        fill="currentColor"
        opacity="0.32"
      />
      <circle cx="14" cy="14" r="1.6" fill="currentColor" />
    </svg>
  );
}

export function Wordmark({
  className,
  compact,
}: {
  className?: string;
  compact?: boolean;
}) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <CompassMark className="shrink-0 text-accent-600 dark:text-accent-400" />
      <span className="flex min-w-0 flex-col leading-none">
        <span className="flex items-baseline gap-1.5">
          <span className="text-[15px] font-semibold tracking-tight">IOMETE</span>
          <span className="text-[15px] font-semibold tracking-[0.14em] text-accent-700 dark:text-accent-400">
            COMPASS
          </span>
        </span>
        {!compact && (
          <span className="mt-1 truncate text-[10px] uppercase tracking-[0.13em] opacity-55">
            Understand · Experience · Resolve · Improve
          </span>
        )}
      </span>
    </span>
  );
}
