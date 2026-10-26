import { RoleGuard } from "@/components/RoleGuard";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <RoleGuard roles={["aicte_viewer", "aicte_officer"]}>{children}</RoleGuard>;
}
