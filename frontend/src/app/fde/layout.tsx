import { OperatorShell } from "@/components/layout/OperatorShell";

export const metadata = { title: "FDE command center" };

export default function FdeLayout({ children }: { children: React.ReactNode }) {
  return <OperatorShell area="fde">{children}</OperatorShell>;
}
