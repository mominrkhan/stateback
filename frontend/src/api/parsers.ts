import { ParseFailure } from "./errors";
import type {
  Approval, AuditEvent, Compensation, CompensationAttempt, ExecutionAttempt, JsonValue,
  NormalizedError, Operation, OperationPage, OperatorOverview, PolicyDecision, PrincipalRef, ProviderEvidence,
  Reconstruction, Reconciliation, SemanticStatus, SemanticSummary,
  VerificationOutcome, VerificationRecord, VerificationRequest, VerificationResult,
} from "./types";

function object(value: unknown, path: string): object {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new ParseFailure(path, "expected object");
  return value;
}
function get(value: object, key: string, path: string): unknown {
  if (!Object.prototype.hasOwnProperty.call(value, key)) throw new ParseFailure(`${path}.${key}`, "required");
  return Reflect.get(value, key);
}
function str(value: unknown, path: string, max = Number.MAX_SAFE_INTEGER): string {
  if (typeof value !== "string" || value.length === 0 || value.length > max) throw new ParseFailure(path, `expected non-empty string <= ${max}`);
  return value;
}
function nullableStr(value: unknown, path: string): string | null { return value === null ? null : str(value, path); }
function timestamp(value: unknown, path: string): string {
  const parsed = str(value, path);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/.test(parsed) || Number.isNaN(Date.parse(parsed))) {
    throw new ParseFailure(path, "expected canonical UTC timestamp");
  }
  return parsed;
}
function nullableTimestamp(value: unknown, path: string): string | null {
  return value === null ? null : timestamp(value, path);
}
function bool(value: unknown, path: string): boolean { if (typeof value !== "boolean") throw new ParseFailure(path, "expected boolean"); return value; }
function integer(value: unknown, path: string, min = 0): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < min) throw new ParseFailure(path, `expected integer >= ${min}`);
  return value;
}
function nullableInteger(value: unknown, path: string, min = 0): number | null { return value === null ? null : integer(value, path, min); }
function array(value: unknown, path: string): unknown[] { if (!Array.isArray(value)) throw new ParseFailure(path, "expected array"); return value; }
function strings(value: unknown, path: string): string[] { return array(value, path).map((item, i) => str(item, `${path}[${i}]`)); }
function version(value: object, path: string): "v1" { if (get(value, "contract_version", path) !== "v1") throw new ParseFailure(`${path}.contract_version`, "unsupported contract version"); return "v1"; }
function json(value: unknown, path: string, depth = 0): JsonValue {
  if (depth > 32) throw new ParseFailure(path, "JSON nesting exceeds 32");
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") { if (!Number.isFinite(value)) throw new ParseFailure(path, "expected finite JSON number"); return value; }
  if (Array.isArray(value)) return value.map((item, index) => json(item, `${path}[${index}]`, depth + 1));
  const raw = object(value, path); const result: Record<string, JsonValue> = {};
  for (const key of Object.keys(raw)) result[key] = json(Reflect.get(raw, key), `${path}.${key}`, depth + 1);
  return result;
}
function metadata(value: unknown, path: string): Readonly<Record<string, string>> {
  const raw = object(value, path); const result: Record<string, string> = {};
  for (const key of Object.keys(raw)) result[key] = str(Reflect.get(raw, key), `${path}.${key}`);
  return result;
}
function principal(value: unknown, path: string): PrincipalRef {
  const raw = object(value, path); return { type: str(get(raw, "type", path), `${path}.type`), id: str(get(raw, "id", path), `${path}.id`), display_name: nullableStr(get(raw, "display_name", path), `${path}.display_name`) };
}
function evidence(value: unknown, path: string): ProviderEvidence {
  const raw = object(value, path); return {
    source: str(get(raw, "source", path), `${path}.source`), provider: str(get(raw, "provider", path), `${path}.provider`), observed_at: timestamp(get(raw, "observed_at", path), `${path}.observed_at`),
    provider_status: nullableStr(get(raw, "provider_status", path), `${path}.provider_status`), provider_request_id: nullableStr(get(raw, "provider_request_id", path), `${path}.provider_request_id`),
    external_operation_id: nullableStr(get(raw, "external_operation_id", path), `${path}.external_operation_id`), external_resource_ids: strings(get(raw, "external_resource_ids", path), `${path}.external_resource_ids`),
    evidence_fields: json(get(raw, "evidence_fields", path), `${path}.evidence_fields`), raw_reference: nullableStr(get(raw, "raw_reference", path), `${path}.raw_reference`),
  };
}
function effect(value: unknown, path: string) {
  const raw = object(value, path);
  return {
    provider: str(get(raw, "provider", path), `${path}.provider`),
    action: str(get(raw, "action", path), `${path}.action`),
    version: str(get(raw, "version", path), `${path}.version`),
  };
}
function normalizedError(value: unknown, path: string): NormalizedError {
  const raw = object(value, path); return { contract_version: version(raw, path), kind: str(get(raw, "kind", path), `${path}.kind`), code: str(get(raw, "code", path), `${path}.code`), message: str(get(raw, "message", path), `${path}.message`), retryable_infrastructure: bool(get(raw, "retryable_infrastructure", path), `${path}.retryable_infrastructure`), provider_http_status: nullableInteger(get(raw, "provider_http_status", path), `${path}.provider_http_status`, 100), provider_error_code: nullableStr(get(raw, "provider_error_code", path), `${path}.provider_error_code`), retry_after_seconds: nullableInteger(get(raw, "retry_after_seconds", path), `${path}.retry_after_seconds`), details: json(get(raw, "details", path), `${path}.details`) };
}

export function parseOperation(value: unknown, path = "operation"): Operation {
  const raw = object(value, path); const intent = object(get(raw, "intent", path), `${path}.intent`); const effect = object(get(intent, "effect", `${path}.intent`), `${path}.intent.effect`);
  return {
    contract_version: version(raw, path), operation_id: str(get(raw, "operation_id", path), `${path}.operation_id`), state: str(get(raw, "state", path), `${path}.state`), version: integer(get(raw, "version", path), `${path}.version`, 1),
    intent: { effect: { provider: str(get(effect, "provider", `${path}.intent.effect`), `${path}.intent.effect.provider`), action: str(get(effect, "action", `${path}.intent.effect`), `${path}.intent.effect.action`), version: str(get(effect, "version", `${path}.intent.effect`), `${path}.intent.effect.version`) }, arguments_mode: str(get(intent, "arguments_mode", `${path}.intent`), `${path}.intent.arguments_mode`), arguments: json(get(intent, "arguments", `${path}.intent`), `${path}.intent.arguments`), arguments_ref: nullableStr(get(intent, "arguments_ref", `${path}.intent`), `${path}.intent.arguments_ref`), canonical_arguments_hash: str(get(intent, "canonical_arguments_hash", `${path}.intent`), `${path}.intent.canonical_arguments_hash`), intent_digest: str(get(intent, "intent_digest", `${path}.intent`), `${path}.intent.intent_digest`), requester: principal(get(intent, "requester", `${path}.intent`), `${path}.intent.requester`), requested_at: timestamp(get(intent, "requested_at", `${path}.intent`), `${path}.intent.requested_at`), metadata: metadata(get(intent, "metadata", `${path}.intent`), `${path}.intent.metadata`) },
    risk_level: str(get(raw, "risk_level", path), `${path}.risk_level`), idempotency_identity: str(get(raw, "idempotency_identity", path), `${path}.idempotency_identity`), current_policy_decision_id: nullableStr(get(raw, "current_policy_decision_id", path), `${path}.current_policy_decision_id`), current_approval_id: nullableStr(get(raw, "current_approval_id", path), `${path}.current_approval_id`), latest_attempt_id: nullableStr(get(raw, "latest_attempt_id", path), `${path}.latest_attempt_id`), latest_verification_id: nullableStr(get(raw, "latest_verification_id", path), `${path}.latest_verification_id`), compensation_id: nullableStr(get(raw, "compensation_id", path), `${path}.compensation_id`), created_at: timestamp(get(raw, "created_at", path), `${path}.created_at`), updated_at: timestamp(get(raw, "updated_at", path), `${path}.updated_at`),
  };
}

export function parseOperationPage(value: unknown): OperationPage {
  const raw = object(value, "list"); return { contract_version: version(raw, "list"), items: array(get(raw, "items", "list"), "list.items").map((item, i) => parseOperation(item, `list.items[${i}]`)), next_cursor: nullableStr(get(raw, "next_cursor", "list"), "list.next_cursor") };
}

export function parseOperatorOverview(value: unknown): OperatorOverview {
  const raw = object(value, "overview");
  const attention = object(get(raw, "attention", "overview"), "overview.attention");
  const active = object(get(raw, "active", "overview"), "overview.active");
  return {
    contract_version: version(raw, "overview"),
    total_operations: integer(get(raw, "total_operations", "overview"), "overview.total_operations"),
    attention: {
      awaiting_approval: integer(get(attention, "awaiting_approval", "overview.attention"), "overview.attention.awaiting_approval"),
      unknown: integer(get(attention, "unknown", "overview.attention"), "overview.attention.unknown"),
      manual_intervention: integer(get(attention, "manual_intervention", "overview.attention"), "overview.attention.manual_intervention"),
      compensation_issues: integer(get(attention, "compensation_issues", "overview.attention"), "overview.attention.compensation_issues"),
    },
    active: {
      executing: integer(get(active, "executing", "overview.active"), "overview.active.executing"),
      verifying: integer(get(active, "verifying", "overview.active"), "overview.active.verifying"),
      compensating: integer(get(active, "compensating", "overview.active"), "overview.active.compensating"),
    },
    recent_operations: array(get(raw, "recent_operations", "overview"), "overview.recent_operations")
      .map((item, index) => parseOperation(item, `overview.recent_operations[${index}]`)),
    providers: array(get(raw, "providers", "overview"), "overview.providers").map((item, index) => {
      const path = `overview.providers[${index}]`;
      const provider = object(item, path);
      return {
        provider: str(get(provider, "provider", path), `${path}.provider`),
        configured: bool(get(provider, "configured", path), `${path}.configured`),
        supported_effects: array(get(provider, "supported_effects", path), `${path}.supported_effects`)
          .map((supported, effectIndex) => effect(supported, `${path}.supported_effects[${effectIndex}]`)),
      };
    }),
  };
}
function policy(value: unknown, path: string): PolicyDecision {
  const raw = object(value, path); const obligations = object(get(raw, "obligations", path), `${path}.obligations`);
  return { contract_version: version(raw, path), policy_decision_id: str(get(raw, "policy_decision_id", path), `${path}.policy_decision_id`), operation_id: str(get(raw, "operation_id", path), `${path}.operation_id`), operation_version: integer(get(raw, "operation_version", path), `${path}.operation_version`, 1), intent_digest: str(get(raw, "intent_digest", path), `${path}.intent_digest`), verdict: str(get(raw, "verdict", path), `${path}.verdict`), reason_codes: strings(get(raw, "reason_codes", path), `${path}.reason_codes`), explanation: nullableStr(get(raw, "explanation", path), `${path}.explanation`), obligations: { require_verification: bool(get(obligations, "require_verification", `${path}.obligations`), `${path}.obligations.require_verification`), max_automatic_execution_attempts: nullableInteger(get(obligations, "max_automatic_execution_attempts", `${path}.obligations`), `${path}.obligations.max_automatic_execution_attempts`), max_automatic_recovery_attempts: nullableInteger(get(obligations, "max_automatic_recovery_attempts", `${path}.obligations`), `${path}.obligations.max_automatic_recovery_attempts`), automatic_compensation_allowed: bool(get(obligations, "automatic_compensation_allowed", `${path}.obligations`), `${path}.obligations.automatic_compensation_allowed`), operator_reason_required: bool(get(obligations, "operator_reason_required", `${path}.obligations`), `${path}.obligations.operator_reason_required`), approval_expires_at: nullableTimestamp(get(obligations, "approval_expires_at", `${path}.obligations`), `${path}.obligations.approval_expires_at`) }, policy_revision: str(get(raw, "policy_revision", path), `${path}.policy_revision`), evaluated_at: timestamp(get(raw, "evaluated_at", path), `${path}.evaluated_at`) };
}
function approval(value: unknown, path: string): Approval { const raw = object(value, path); const actor = get(raw, "decided_by", path); return { contract_version: version(raw, path), approval_id: str(get(raw, "approval_id", path), `${path}.approval_id`), operation_id: str(get(raw, "operation_id", path), `${path}.operation_id`), operation_version: integer(get(raw, "operation_version", path), `${path}.operation_version`, 1), intent_digest: str(get(raw, "intent_digest", path), `${path}.intent_digest`), policy_decision_id: str(get(raw, "policy_decision_id", path), `${path}.policy_decision_id`), state: str(get(raw, "state", path), `${path}.state`), requested_at: timestamp(get(raw, "requested_at", path), `${path}.requested_at`), expires_at: nullableTimestamp(get(raw, "expires_at", path), `${path}.expires_at`), decided_at: nullableTimestamp(get(raw, "decided_at", path), `${path}.decided_at`), decided_by: actor === null ? null : principal(actor, `${path}.decided_by`), reason: nullableStr(get(raw, "reason", path), `${path}.reason`) }; }
function attempt(value: unknown, path: string): ExecutionAttempt { const raw = object(value, path); const ev = get(raw, "evidence", path); const err = get(raw, "error", path); return { contract_version: version(raw, path), attempt_id: str(get(raw, "attempt_id", path), `${path}.attempt_id`), operation_id: str(get(raw, "operation_id", path), `${path}.operation_id`), attempt_number: integer(get(raw, "attempt_number", path), `${path}.attempt_number`, 1), state: str(get(raw, "state", path), `${path}.state`), started_at: timestamp(get(raw, "started_at", path), `${path}.started_at`), completed_at: nullableTimestamp(get(raw, "completed_at", path), `${path}.completed_at`), provider_idempotency_key: nullableStr(get(raw, "provider_idempotency_key", path), `${path}.provider_idempotency_key`), external_operation_id: nullableStr(get(raw, "external_operation_id", path), `${path}.external_operation_id`), external_resource_ids: strings(get(raw, "external_resource_ids", path), `${path}.external_resource_ids`), outcome: nullableStr(get(raw, "outcome", path), `${path}.outcome`), evidence: ev === null ? null : evidence(ev, `${path}.evidence`), error: err === null ? null : normalizedError(err, `${path}.error`), correlation_id: nullableStr(get(raw, "correlation_id", path), `${path}.correlation_id`) }; }
function reconciliation(value: unknown, path: string): Reconciliation { const raw = object(value, path); const decision = object(get(raw, "decision", path), `${path}.decision`); return { reconciliation_decision_id: str(get(raw, "reconciliation_decision_id", path), `${path}.reconciliation_decision_id`), operation_id: str(get(raw, "operation_id", path), `${path}.operation_id`), operation_version: integer(get(raw, "operation_version", path), `${path}.operation_version`, 1), verification_id: nullableStr(get(raw, "verification_id", path), `${path}.verification_id`), decision: { action: str(get(decision, "action", `${path}.decision`), `${path}.decision.action`), reason_code: str(get(decision, "reason_code", `${path}.decision`), `${path}.decision.reason_code`) }, created_at: timestamp(get(raw, "created_at", path), `${path}.created_at`) }; }
function verification(value: unknown, path: string): VerificationRecord {
  const raw = object(value, path);
  const requestPath = `${path}.request`;
  const requestRaw = object(get(raw, "request", path), requestPath);
  const target = str(get(requestRaw, "target", requestPath), `${requestPath}.target`);
  if (target !== "ORIGINAL_EFFECT" && target !== "COMPENSATION") throw new ParseFailure(`${requestPath}.target`, "unknown verification target");
  const request: VerificationRequest = {
    contract_version: version(requestRaw, requestPath),
    verification_id: str(get(requestRaw, "verification_id", requestPath), `${requestPath}.verification_id`),
    operation_id: str(get(requestRaw, "operation_id", requestPath), `${requestPath}.operation_id`),
    operation_version: integer(get(requestRaw, "operation_version", requestPath), `${requestPath}.operation_version`, 1),
    target,
    target_attempt_id: nullableStr(get(requestRaw, "target_attempt_id", requestPath), `${requestPath}.target_attempt_id`),
    effect: effect(get(requestRaw, "effect", requestPath), `${requestPath}.effect`),
    external_operation_id: nullableStr(get(requestRaw, "external_operation_id", requestPath), `${requestPath}.external_operation_id`),
    external_resource_ids: strings(get(requestRaw, "external_resource_ids", requestPath), `${requestPath}.external_resource_ids`),
    idempotency_identity: str(get(requestRaw, "idempotency_identity", requestPath), `${requestPath}.idempotency_identity`),
    provider_evidence_refs: strings(get(requestRaw, "provider_evidence_refs", requestPath), `${requestPath}.provider_evidence_refs`),
    requested_at: timestamp(get(requestRaw, "requested_at", requestPath), `${requestPath}.requested_at`),
  };
  const resultValue = get(raw, "result", path);
  const result: VerificationResult | null = resultValue === null ? null : (() => {
    const resultPath = `${path}.result`;
    const resultRaw = object(resultValue, resultPath);
    const outcomeValue = str(get(resultRaw, "outcome", resultPath), `${resultPath}.outcome`);
    if (!["APPLIED", "NOT_APPLIED", "UNKNOWN"].includes(outcomeValue)) throw new ParseFailure(`${resultPath}.outcome`, "unknown verification outcome");
    const outcome = outcomeValue as VerificationOutcome;
    const errorValue = get(resultRaw, "error", resultPath);
    return {
      contract_version: version(resultRaw, resultPath),
      verification_id: str(get(resultRaw, "verification_id", resultPath), `${resultPath}.verification_id`),
      outcome, evidence: evidence(get(resultRaw, "evidence", resultPath), `${resultPath}.evidence`),
      error: errorValue === null ? null : normalizedError(errorValue, `${resultPath}.error`),
      completed_at: timestamp(get(resultRaw, "completed_at", resultPath), `${resultPath}.completed_at`),
    };
  })();
  return { request, result };
}
function compensation(value: unknown, path: string): Compensation { const raw = object(value, path); return { contract_version: version(raw, path), compensation_id: str(get(raw, "compensation_id", path), `${path}.compensation_id`), original_operation_id: str(get(raw, "original_operation_id", path), `${path}.original_operation_id`), kind: str(get(raw, "kind", path), `${path}.kind`), state: str(get(raw, "state", path), `${path}.state`), version: integer(get(raw, "version", path), `${path}.version`, 1), intent_digest: str(get(raw, "intent_digest", path), `${path}.intent_digest`), arguments_mode: str(get(raw, "arguments_mode", path), `${path}.arguments_mode`), arguments: json(get(raw, "arguments", path), `${path}.arguments`), arguments_ref: nullableStr(get(raw, "arguments_ref", path), `${path}.arguments_ref`), idempotency_identity: str(get(raw, "idempotency_identity", path), `${path}.idempotency_identity`), requested_by: principal(get(raw, "requested_by", path), `${path}.requested_by`), policy_decision_id: nullableStr(get(raw, "policy_decision_id", path), `${path}.policy_decision_id`), created_at: timestamp(get(raw, "created_at", path), `${path}.created_at`), updated_at: timestamp(get(raw, "updated_at", path), `${path}.updated_at`) }; }
function compensationAttempt(value: unknown, path: string): CompensationAttempt { const raw = object(value, path); const ev = get(raw, "evidence", path); const err = get(raw, "error", path); return { contract_version: version(raw, path), compensation_attempt_id: str(get(raw, "compensation_attempt_id", path), `${path}.compensation_attempt_id`), compensation_id: str(get(raw, "compensation_id", path), `${path}.compensation_id`), attempt_number: integer(get(raw, "attempt_number", path), `${path}.attempt_number`, 1), state: str(get(raw, "state", path), `${path}.state`), started_at: timestamp(get(raw, "started_at", path), `${path}.started_at`), completed_at: nullableTimestamp(get(raw, "completed_at", path), `${path}.completed_at`), provider_idempotency_key: nullableStr(get(raw, "provider_idempotency_key", path), `${path}.provider_idempotency_key`), external_operation_id: nullableStr(get(raw, "external_operation_id", path), `${path}.external_operation_id`), outcome: nullableStr(get(raw, "outcome", path), `${path}.outcome`), evidence: ev === null ? null : evidence(ev, `${path}.evidence`), error: err === null ? null : normalizedError(err, `${path}.error`) }; }
function audit(value: unknown, path: string): AuditEvent { const raw = object(value, path); const actor = get(raw, "actor", path); return { contract_version: version(raw, path), audit_event_id: str(get(raw, "audit_event_id", path), `${path}.audit_event_id`), operation_id: str(get(raw, "operation_id", path), `${path}.operation_id`), sequence: integer(get(raw, "sequence", path), `${path}.sequence`, 1), event_type: str(get(raw, "event_type", path), `${path}.event_type`), from_state: nullableStr(get(raw, "from_state", path), `${path}.from_state`), to_state: nullableStr(get(raw, "to_state", path), `${path}.to_state`), operation_version: integer(get(raw, "operation_version", path), `${path}.operation_version`, 1), actor: actor === null ? null : principal(actor, `${path}.actor`), reason_code: str(get(raw, "reason_code", path), `${path}.reason_code`), data: json(get(raw, "data", path), `${path}.data`), correlation_id: nullableStr(get(raw, "correlation_id", path), `${path}.correlation_id`), created_at: timestamp(get(raw, "created_at", path), `${path}.created_at`) }; }
function mapped<T>(value: unknown, path: string, parser: (item: unknown, itemPath: string) => T): T[] { return array(value, path).map((item, i) => parser(item, `${path}[${i}]`)); }

export function parseReconstruction(value: unknown): Reconstruction {
  const raw = object(value, "reconstruction");
  const comp = get(raw, "compensation", "reconstruction");
  return { contract_version: version(raw, "reconstruction"), operation: parseOperation(get(raw, "operation", "reconstruction"), "reconstruction.operation"), policy_decisions: mapped(get(raw, "policy_decisions", "reconstruction"), "reconstruction.policy_decisions", policy), approvals: mapped(get(raw, "approvals", "reconstruction"), "reconstruction.approvals", approval), attempts: mapped(get(raw, "attempts", "reconstruction"), "reconstruction.attempts", attempt), verifications: mapped(get(raw, "verifications", "reconstruction"), "reconstruction.verifications", verification), reconciliations: mapped(get(raw, "reconciliations", "reconstruction"), "reconstruction.reconciliations", reconciliation), compensation: comp === null ? null : compensation(comp, "reconstruction.compensation"), compensation_attempts: mapped(get(raw, "compensation_attempts", "reconstruction"), "reconstruction.compensation_attempts", compensationAttempt), audit: mapped(get(raw, "audit", "reconstruction"), "reconstruction.audit", audit), available_actions: strings(get(raw, "available_actions", "reconstruction"), "reconstruction.available_actions") };
}

export function parseSemanticSummary(value: unknown): SemanticSummary {
  const raw = object(value, "semantic"); const statusRaw = str(get(raw, "status", "semantic"), "semantic.status");
  if (!["AVAILABLE", "ABSTAINED", "UNAVAILABLE", "INVALID"].includes(statusRaw)) throw new ParseFailure("semantic.status", "unknown status");
  const status: SemanticStatus = statusRaw === "AVAILABLE" ? "AVAILABLE" : statusRaw === "ABSTAINED" ? "ABSTAINED" : statusRaw === "UNAVAILABLE" ? "UNAVAILABLE" : "INVALID";
  const events = array(get(raw, "key_events", "semantic"), "semantic.key_events"); if (events.length > 20) throw new ParseFailure("semantic.key_events", "limit 20");
  const uncertainties = strings(get(raw, "unresolved_uncertainties", "semantic"), "semantic.unresolved_uncertainties"); if (uncertainties.length > 20 || uncertainties.some((item) => item.length > 500)) throw new ParseFailure("semantic.unresolved_uncertainties", "limit exceeded");
  const summary = nullableStr(get(raw, "summary", "semantic"), "semantic.summary"); if (summary !== null && summary.length > 2000) throw new ParseFailure("semantic.summary", "limit 2000");
  const confidenceRaw = get(raw, "confidence", "semantic"); const confidence = confidenceRaw === null ? null : typeof confidenceRaw === "number" && Number.isFinite(confidenceRaw) && confidenceRaw >= 0 && confidenceRaw <= 1 ? confidenceRaw : (() => { throw new ParseFailure("semantic.confidence", "expected number 0..1 or null"); })();
  if (status === "AVAILABLE" && (summary === null || confidence === null)) throw new ParseFailure("semantic", "status/content mismatch");
  if (status === "AVAILABLE" && confidence !== null && confidence < 0.5) throw new ParseFailure("semantic.confidence", "AVAILABLE requires confidence >= 0.5");
  if (status !== "AVAILABLE" && (summary !== null || confidence !== null || events.length !== 0 || uncertainties.length !== 0)) throw new ParseFailure("semantic", "status/content mismatch");
  const provenance = object(get(raw, "provenance", "semantic"), "semantic.provenance"); if (get(provenance, "prompt_version", "semantic.provenance") !== "audit-summary-v1" || get(provenance, "output_schema_version", "semantic.provenance") !== "v1") throw new ParseFailure("semantic.provenance", "unsupported provenance version");
  const summarizedThrough = integer(get(raw, "summarized_through_sequence", "semantic"), "semantic.summarized_through_sequence");
  const keyEvents = events.map((item, i) => { const event = object(item, `semantic.key_events[${i}]`); const sequence = integer(get(event, "sequence", `semantic.key_events[${i}]`), `semantic.key_events[${i}].sequence`, 1); if (sequence > summarizedThrough) throw new ParseFailure(`semantic.key_events[${i}].sequence`, "not present in summarized timeline"); return { sequence, description: str(get(event, "description", `semantic.key_events[${i}]`), `semantic.key_events[${i}].description`, 500) }; });
  return { contract_version: version(raw, "semantic"), advisory: get(raw, "advisory", "semantic") === true ? true : (() => { throw new ParseFailure("semantic.advisory", "expected true"); })(), status, summary, key_events: keyEvents, unresolved_uncertainties: uncertainties, confidence, summarized_operation_version: integer(get(raw, "summarized_operation_version", "semantic"), "semantic.summarized_operation_version", 1), summarized_through_sequence: summarizedThrough, provenance: { provider: nullableStr(get(provenance, "provider", "semantic.provenance"), "semantic.provenance.provider"), model: nullableStr(get(provenance, "model", "semantic.provenance"), "semantic.provenance.model"), prompt_version: "audit-summary-v1", output_schema_version: "v1" }, reason_code: str(get(raw, "reason_code", "semantic"), "semantic.reason_code", 200) };
}

export function parseApiError(value: unknown, status: number): import("./errors").ApiErrorDetails {
  const envelope = object(value, "error_envelope"); version(envelope, "error_envelope"); const raw = object(get(envelope, "error", "error_envelope"), "error_envelope.error");
  return { status, code: str(get(raw, "code", "error_envelope.error"), "error_envelope.error.code"), safeMessage: str(get(raw, "message", "error_envelope.error"), "error_envelope.error.message"), retryable: bool(get(raw, "retryable", "error_envelope.error"), "error_envelope.error.retryable"), correlationId: nullableStr(get(raw, "correlation_id", "error_envelope.error"), "error_envelope.error.correlation_id") };
}
