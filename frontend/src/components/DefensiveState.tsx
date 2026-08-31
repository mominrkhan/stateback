import type { ReactNode } from "react";
import { AlertTriangle, CircleSlash2, LoaderCircle, SearchX, ShieldAlert } from "lucide-react";

export type DefensiveStateKind = "loading" | "empty" | "error" | "unauthorized" | "forbidden" | "unsupported";

export interface DefensiveStateProps {
  kind: DefensiveStateKind;
  title: string;
  children?: ReactNode;
  onRetry?: () => void;
}

export function DefensiveState({ kind, title, children, onRetry }: DefensiveStateProps) {
  const liveRole = kind === "error" || kind === "unauthorized" || kind === "forbidden"
    ? "alert"
    : "status";
  const Icon = kind === "loading" ? LoaderCircle : kind === "empty" ? SearchX : kind === "unsupported" ? ShieldAlert : kind === "error" ? AlertTriangle : CircleSlash2;

  return (
    <section className={`defensive-state defensive-state--${kind}`} role={liveRole} aria-busy={kind === "loading" || undefined}>
      <span className="defensive-state__icon" aria-hidden="true"><Icon size={20} /></span>
      <h2>{title}</h2>
      {children && <div>{children}</div>}
      {onRetry && (
        <button type="button" className="primitive-button" onClick={onRetry}>Retry</button>
      )}
    </section>
  );
}
