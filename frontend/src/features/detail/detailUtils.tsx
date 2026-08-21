import type { PrincipalRef } from "../../api/types";

export function Principal({ principal }: { principal: PrincipalRef | null }) {
  if (!principal) return <span>Not recorded</span>;
  return (
    <span>
      {principal.display_name ? `${principal.display_name} — ` : ""}
      {principal.type}: {principal.id}
    </span>
  );
}

export function EmptyDetail({ children }: { children: string }) {
  return <p className="detail-empty">{children}</p>;
}
