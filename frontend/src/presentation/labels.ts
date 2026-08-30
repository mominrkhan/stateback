import type { EffectRef, OperationState, PrincipalRef } from "../api/types";

const STATE_LABELS: Record<OperationState, string> = {
  PENDING_POLICY: "Pending policy",
  AWAITING_APPROVAL: "Awaiting approval",
  READY: "Ready",
  EXECUTING: "Executing",
  VERIFYING: "Verifying external outcome",
  UNKNOWN: "Outcome unknown",
  SUCCEEDED: "Succeeded",
  FAILED: "Failed",
  DENIED: "Denied",
  CANCELLED: "Cancelled",
  COMPENSATING: "Compensation in progress",
  COMPENSATION_UNKNOWN: "Compensation outcome unknown",
  COMPENSATED: "Compensated",
  COMPENSATION_FAILED: "Compensation failed",
  MANUAL_INTERVENTION: "Manual intervention",
};

export function operationStateLabel(state: string): string | null {
  return Object.prototype.hasOwnProperty.call(STATE_LABELS, state)
    ? STATE_LABELS[state as OperationState]
    : null;
}

export function providerLabel(provider: string): string {
  return provider === "github" ? "GitHub" : "Unsupported provider";
}

export function actionLabel(effect: EffectRef): string {
  if (effect.provider === "github" && effect.version === "v1") {
    const labels: Record<string, string> = {
      create_issue: "Create issue",
      create_issue_comment: "Comment on issue",
      add_label: "Add label",
      create_pull_request: "Create pull request",
      merge_pull_request: "Merge pull request",
    };
    return labels[effect.action] ?? "Unsupported effect";
  }
  return "Unsupported effect";
}

export function effectIdentifier(effect: EffectRef): string {
  return `${effect.provider}.${effect.action}.${effect.version}`;
}

export function requesterLabel(requester: PrincipalRef): string {
  return requester.display_name ?? requester.id;
}
