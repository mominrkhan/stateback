import type { ActionKey } from "../api/types";

export const ACTION_LABELS: Readonly<Record<ActionKey, string>> = {
  approve: "Approve operation", reject: "Reject operation", verify: "Request verification",
  compensate: "Start compensation", retry_compensation: "Retry compensation",
  escalate_compensation: "Escalate compensation",
};
const KNOWN = new Set<string>(Object.keys(ACTION_LABELS));
function diagnostic(value: string): string { return value.replace(/[^\x20-\x7e]/g, "�").slice(0, 100); }

export interface ActionGateProps { availableActions: readonly string[]; disabled?: boolean; onAction: (action: ActionKey) => void }
export function ActionGate({ availableActions, disabled = false, onAction }: ActionGateProps) {
  const distinct = [...new Set(availableActions)];
  const known = distinct.filter((value): value is ActionKey => KNOWN.has(value));
  const unknown = distinct.filter((value) => !KNOWN.has(value));
  return <div className="action-gate" aria-label="Available operator actions">
    {known.map((action) => <button className="primitive-button primitive-button--danger" key={action} type="button" disabled={disabled} onClick={() => onAction(action)}>{ACTION_LABELS[action]}</button>)}
    {unknown.map((action, index) => <p key={`${action}-${index}`} role="status">Unsupported action unavailable: <code>{diagnostic(action)}</code></p>)}
  </div>;
}
