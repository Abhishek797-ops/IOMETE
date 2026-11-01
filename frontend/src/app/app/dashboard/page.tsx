import { redirect } from "next/navigation";

/**
 * The portal entry point.
 *
 * Redirects to support rather than showing a metrics page first: a customer opening
 * COMPASS is almost always here because something is broken, and a dashboard would put a
 * chart between them and the resolution that is waiting.
 */
export default function PortalDashboardPage() {
  redirect("/app/support");
}
