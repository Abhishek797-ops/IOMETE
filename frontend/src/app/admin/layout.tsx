import { OperatorShell } from "@/components/layout/OperatorShell";

export const metadata = { title: "Administration" };

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <OperatorShell area="admin">{children}</OperatorShell>;
}
