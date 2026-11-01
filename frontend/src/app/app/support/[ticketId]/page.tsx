import { TicketWorkspace } from "./TicketWorkspace";

export const metadata = { title: "Ticket" };

/**
 * One ticket, with Resolution Replay.
 *
 * A thin server shell: the ticket is tenant-scoped and every fetch has to carry the
 * viewer's token, so the work happens client-side where that token lives.
 */
export default async function TicketPage({
  params,
}: {
  params: Promise<{ ticketId: string }>;
}) {
  const { ticketId } = await params;
  return <TicketWorkspace ticketId={ticketId} />;
}
