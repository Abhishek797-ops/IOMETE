import { OperatorShell } from "@/components/layout/OperatorShell";

export const metadata = { title: "Customer portal" };

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  return <OperatorShell area="portal">{children}</OperatorShell>;
}
