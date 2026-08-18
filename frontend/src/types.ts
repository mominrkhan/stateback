export const KNOWN_STATES = [
  "PENDING_POLICY",
  "AWAITING_APPROVAL",
  "READY",
  "EXECUTING",
  "VERIFYING",
  "UNKNOWN",
  "SUCCEEDED",
  "FAILED",
  "DENIED",
  "CANCELLED",
  "COMPENSATING",
  "COMPENSATION_UNKNOWN",
  "COMPENSATED",
  "COMPENSATION_FAILED",
  "MANUAL_INTERVENTION",
] as const;

export type KnownState = (typeof KNOWN_STATES)[number];

export interface Operation {
  contract_version: "v1";
  operation_id: string;
  state: string;
  version: number;
  created_at: string;
  updated_at: string;
  intent: {
    effect: { provider: string; action: string; version: string };
  };
  current_approval_id: string | null;
  compensation_id: string | null;
}

export interface AuditEvent {
  audit_event_id: string;
  sequence: number;
  event_type: string;
  reason_code: string;
  from_state: string | null;
  to_state: string | null;
  correlation_id: string | null;
  created_at: string;
}

export interface Reconstruction {
  contract_version: "v1";
  operation: Operation;
  audit: AuditEvent[];
  available_actions: string[];
}

export interface SemanticSummary {
  contract_version: "v1";
  advisory: true;
  status: string;
  summary: string | null;
  key_events: Array<{ sequence: number; description: string }>;
  unresolved_uncertainties: string[];
  confidence: number | null;
  summarized_operation_version: number;
  summarized_through_sequence: number;
  provenance: {
    provider: string | null;
    model: string | null;
    prompt_version: string;
    output_schema_version: string;
  };
  reason_code: string;
}

export function isKnownState(state: string): state is KnownState {
  return (KNOWN_STATES as readonly string[]).includes(state);
}
