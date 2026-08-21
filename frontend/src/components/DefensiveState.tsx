import type { ReactNode } from "react";

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

  return (
    <section className={`defensive-state defensive-state--${kind}`} role={liveRole} aria-busy={kind === "loading" || undefined}>
      <h2>{title}</h2>
      {children && <div>{children}</div>}
      {onRetry && (
        <button type="button" className="primitive-button" onClick={onRetry}>Retry</button>
      )}
    </section>
  );
}
