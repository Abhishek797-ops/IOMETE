import { PublicShell } from "@/components/layout/PublicShell";

/**
 * The public route group.
 *
 * A group rather than a path prefix because these pages live at different top-level URLs
 * (`/`, `/explore`, `/fit-finder`, …) but share one shell. Putting the header, footer and
 * demo banner here means a new public page gets all three by existing.
 */
export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return <PublicShell>{children}</PublicShell>;
}
