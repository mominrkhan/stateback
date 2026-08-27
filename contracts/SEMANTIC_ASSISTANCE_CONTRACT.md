# Stateback Semantic Assistance Contract v1

**Status:** Canonical
**Version:** `v1`
**Owns:** optional operator-requested audit-history summary semantics

## Accepted use case

Phase 16 implements one use case: an authenticated operator may request a
read-only advisory summary of an operation's authoritative audit history.

The summary helps operator triage. It is not provider evidence, policy input,
authorization, a control request, or canonical operation state. No other
semantic-AI use case is accepted by this contract.

## Operator boundary

`POST /v1/operator/operations/{operation_id}/semantic-summary` requires the
`OPERATOR` role. It invokes no provider and performs no lifecycle, policy,
approval, recovery, reconciliation, compensation, or audit mutation.

The strict request body is `{"contract_version":"v1"}`. Unknown fields or
unsupported versions are rejected through the existing request-validation
error contract.

The endpoint returns HTTP 200 when semantic assistance is available,
abstaining, unavailable, or invalid. Authentication, authorization, missing
operation, and malformed identifier errors retain the existing operator API
semantics.

## Model input

The server constructs model input from the authorized operation
reconstruction. The input is limited to:

- effect provider, action, and version;
- canonical operation state and version; and
- at most 200 ordered audit events containing sequence, event type, reason
  code, from/to state, and timestamp.

Raw intent arguments, audit `data`, actors, correlation identifiers, provider
payloads/evidence, credentials, and secrets MUST NOT be sent to the model.
Values matching canonical secret rejection rules are replaced by a redaction
marker. If the timeline exceeds 200 events, the service abstains without model
invocation.

## Response

```text
SemanticSummary {
  contract_version: "v1"
  advisory: true
  status: AVAILABLE | ABSTAINED | UNAVAILABLE | INVALID
  summary: optional<string>
  key_events: list<SemanticKeyEvent>
  unresolved_uncertainties: list<string>
  confidence: optional<number>
  summarized_operation_version: integer
  summarized_through_sequence: integer
  provenance: SemanticProvenance
  reason_code: string
}

SemanticKeyEvent {
  sequence: integer
  description: string
}

SemanticProvenance {
  provider: optional<string>
  model: optional<string>
  prompt_version: "audit-summary-v1"
  output_schema_version: "v1"
}
```

`summary` is at most 2,000 characters. At most 20 key events and 20 unresolved
uncertainties are accepted; each description is at most 500 characters.
`confidence`, when present, is between 0 and 1. A confidence below 0.5 becomes
`ABSTAINED`. Key-event sequences must exist in the supplied audit timeline.

Only `AVAILABLE` contains summary content. Every other status has null summary
and confidence plus empty content lists. Unknown fields, values, schema
versions, non-finite numbers, oversize content, and output larger than 64 KiB
produce `INVALID`.

The server, not the model, supplies provenance and summarized version/sequence.
Model claims about identity, authority, external truth, operation state, or
provenance are ignored.

## Failure and fallback

- No configured semantic service produces `UNAVAILABLE` with
  `semantic_not_configured`.
- Timeout, connection failure, or model-service failure produces `UNAVAILABLE`
  with a stable safe reason code.
- Explicit model abstention or low confidence produces `ABSTAINED`.
- Malformed or misleading structured output produces `INVALID`.

All outcomes leave deterministic reconstruction and operator controls usable.
Semantic output MUST NOT resolve `UNKNOWN`, prove an effect or compensation,
authorize an action, alter available actions, or create an audit/lifecycle
transition.

## Model integration

The accepted production-shaped integration is optional local Ollama over its
loopback HTTP API. Configuration must explicitly supply the local base URL,
model name, and timeout. The adapter rejects non-loopback destinations, sends
no credentials, disables streaming, requests a JSON-schema response, and makes
no network request at import or application startup.

Correctness tests use deterministic fakes. A live Ollama evaluation is optional
and non-gating.
