const STATE_GROUPS = {
  info: ["PENDING_POLICY", "AWAITING_APPROVAL", "READY"],
  active: ["EXECUTING", "COMPENSATING"],
  unresolved: ["VERIFYING", "UNKNOWN", "COMPENSATION_UNKNOWN", "MANUAL_INTERVENTION"],
  success: ["SUCCEEDED", "COMPENSATED"],
  failure: ["FAILED", "DENIED", "COMPENSATION_FAILED"],
  neutral: ["CANCELLED"],
} as const;

export type StateGroup = keyof typeof STATE_GROUPS | "unsupported";

export function stateGroup(state: string): StateGroup {
  for (const [group, states] of Object.entries(STATE_GROUPS)) {
    if ((states as readonly string[]).includes(state)) return group as keyof typeof STATE_GROUPS;
  }
  return "unsupported";
}

export function StateBadge({ state }: { state: string }) {
  const group = stateGroup(state);
  const label = group === "unsupported"
    ? `Unsupported state: ${state}`
    : state.replaceAll("_", " ");

  return <span className={`state-badge state-badge--${group}`}>{label}</span>;
}
