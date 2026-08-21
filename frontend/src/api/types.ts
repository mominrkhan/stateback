export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export const OPERATION_STATES = [
  "PENDING_POLICY", "AWAITING_APPROVAL", "READY", "EXECUTING", "VERIFYING",
  "UNKNOWN", "SUCCEEDED", "FAILED", "DENIED", "CANCELLED", "COMPENSATING",
  "COMPENSATION_UNKNOWN", "COMPENSATED", "COMPENSATION_FAILED", "MANUAL_INTERVENTION",
] as const;

export type OperationState = (typeof OPERATION_STATES)[number];
export type ActionKey = "approve" | "reject" | "verify" | "compensate" | "retry_compensation" | "escalate_compensation";

export interface EffectRef { provider: string; action: string; version: string }
export interface PrincipalRef { type: string; id: string; display_name: string | null }
export interface IntentEnvelope {
  effect: EffectRef;
  arguments_mode: string;
  arguments: JsonValue;
  arguments_ref: string | null;
  canonical_arguments_hash: string;
  intent_digest: string;
  requester: PrincipalRef;
  requested_at: string;
  metadata: Readonly<Record<string, string>>;
}

export interface Operation {
  contract_version: "v1";
  operation_id: string;
  state: string;
  version: number;
  intent: IntentEnvelope;
  risk_level: string;
  idempotency_identity: string;
  current_policy_decision_id: string | null;
  current_approval_id: string | null;
  latest_attempt_id: string | null;
  latest_verification_id: string | null;
  compensation_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface OperationPage { contract_version: "v1"; items: Operation[]; next_cursor: string | null }
export interface PolicyObligations {
  require_verification: boolean;
  max_automatic_execution_attempts: number | null;
  max_automatic_recovery_attempts: number | null;
  automatic_compensation_allowed: boolean;
  operator_reason_required: boolean;
  approval_expires_at: string | null;
}
export interface PolicyDecision {
  contract_version: "v1"; policy_decision_id: string; operation_id: string;
  operation_version: number; intent_digest: string; verdict: string; reason_codes: string[];
  explanation: string | null; obligations: PolicyObligations; policy_revision: string; evaluated_at: string;
}
export interface Approval {
  contract_version: "v1"; approval_id: string; operation_id: string; operation_version: number;
  intent_digest: string; policy_decision_id: string; state: string; requested_at: string;
  expires_at: string | null; decided_at: string | null; decided_by: PrincipalRef | null; reason: string | null;
}
export interface ProviderEvidence {
  source: string; provider: string; observed_at: string; provider_status: string | null;
  provider_request_id: string | null; external_operation_id: string | null;
  external_resource_ids: string[]; evidence_fields: JsonValue; raw_reference: string | null;
}
export interface NormalizedError {
  contract_version: "v1"; kind: string; code: string; message: string;
  retryable_infrastructure: boolean; provider_http_status: number | null;
  provider_error_code: string | null; retry_after_seconds: number | null; details: JsonValue;
}
export interface ExecutionAttempt {
  contract_version: "v1"; attempt_id: string; operation_id: string; attempt_number: number; state: string;
  started_at: string; completed_at: string | null; provider_idempotency_key: string | null;
  external_operation_id: string | null; external_resource_ids: string[]; outcome: string | null;
  evidence: ProviderEvidence | null; error: NormalizedError | null; correlation_id: string | null;
}
export interface ReconciliationDecision { action: string; reason_code: string }
export interface Reconciliation {
  reconciliation_decision_id: string; operation_id: string; operation_version: number;
  verification_id: string | null; decision: ReconciliationDecision; created_at: string;
}
export interface Compensation {
  contract_version: "v1"; compensation_id: string; original_operation_id: string; kind: string;
  state: string; version: number; intent_digest: string; arguments_mode: string; arguments: JsonValue;
  arguments_ref: string | null; idempotency_identity: string; requested_by: PrincipalRef;
  policy_decision_id: string | null; created_at: string; updated_at: string;
}
export interface CompensationAttempt {
  contract_version: "v1"; compensation_attempt_id: string; compensation_id: string; attempt_number: number;
  state: string; started_at: string; completed_at: string | null; provider_idempotency_key: string | null;
  external_operation_id: string | null; outcome: string | null; evidence: ProviderEvidence | null;
  error: NormalizedError | null;
}
export interface AuditEvent {
  contract_version: "v1"; audit_event_id: string; operation_id: string; sequence: number;
  event_type: string; from_state: string | null; to_state: string | null; operation_version: number;
  actor: PrincipalRef | null; reason_code: string; data: JsonValue; correlation_id: string | null; created_at: string;
}
export interface Reconstruction {
  contract_version: "v1"; operation: Operation; policy_decisions: PolicyDecision[]; approvals: Approval[];
  attempts: ExecutionAttempt[]; verifications: never[]; reconciliations: Reconciliation[];
  compensation: Compensation | null; compensation_attempts: CompensationAttempt[]; audit: AuditEvent[];
  available_actions: string[];
}
export type SemanticStatus = "AVAILABLE" | "ABSTAINED" | "UNAVAILABLE" | "INVALID";
export interface SemanticSummary {
  contract_version: "v1"; advisory: true; status: SemanticStatus; summary: string | null;
  key_events: Array<{ sequence: number; description: string }>; unresolved_uncertainties: string[];
  confidence: number | null; summarized_operation_version: number; summarized_through_sequence: number;
  provenance: { provider: string | null; model: string | null; prompt_version: "audit-summary-v1"; output_schema_version: "v1" };
  reason_code: string;
}
export interface CommandAttempt {
  operationId: string; actionKey: ActionKey; expectedVersion: number; approvalId?: string;
  reason: string; idempotencyKey: string; correlationId: string;
}
