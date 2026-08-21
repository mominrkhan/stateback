import type { ReactNode } from "react";

export type CommandOutcomeKind =
  | "submitting"
  | "accepted"
  | "accepted-reloading"
  | "authoritative-reloaded"
  | "conflict"
  | "forbidden"
  | "rate-limited"
  | "validation-error"
  | "transport-error"
  | "error";

export interface CommandOutcomeProps {
  kind: CommandOutcomeKind;
  title: string;
  children: ReactNode;
}

export function CommandOutcome({ kind, title, children }: CommandOutcomeProps) {
  const assertive = ["conflict", "forbidden", "rate-limited", "validation-error", "transport-error", "error"].includes(kind);
  return (
    <section
      className={`command-outcome command-outcome--${kind}`}
      role={assertive ? "alert" : "status"}
      aria-busy={kind === "submitting" || kind === "accepted-reloading" || undefined}
    >
      <strong className="command-outcome__title">{title}</strong>
      <div>{children}</div>
    </section>
  );
}
