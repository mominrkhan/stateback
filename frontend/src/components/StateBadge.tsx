import { CircleCheck, CircleHelp, CircleX, Clock3, ScanSearch, ShieldAlert, type LucideIcon } from "lucide-react";

import { operationStateLabel } from "../presentation/labels";

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
  const label = operationStateLabel(state) ?? `Unsupported state: ${state}`;
  const icons: Record<StateGroup, LucideIcon> = { info: Clock3, active: ScanSearch, unresolved: state === "UNKNOWN" ? CircleHelp : state === "VERIFYING" ? ScanSearch : ShieldAlert, success: CircleCheck, failure: CircleX, neutral: Clock3, unsupported: ShieldAlert };
  const Icon = icons[group];

  return <span className={`state-badge state-badge--${group}`} title={group === "unsupported" ? undefined : `Canonical state: ${state}`}><Icon size={13} aria-hidden="true" />{label}</span>;
}
