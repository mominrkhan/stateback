# Policy and Approval Contract

**Status:** Canonical v1
**Owns:** policy verdicts, policy inputs, obligations, approval binding, stale-approval rules.

---

## 1. Policy verdict

Canonical `PolicyVerdict`:

```text
ALLOW
DENY
REQUIRE_APPROVAL
```

A policy verdict answers whether the operation may proceed from a control/risk perspective. It does not claim anything about provider execution.

---

## 2. `PolicyDecision`

```text
PolicyDecision {
  contract_version: "v1"
  policy_decision_id: opaque_id
  operation_id: opaque_id
  operation_version: integer
  intent_digest: string

  verdict: PolicyVerdict
  reason_codes: list<string>
  explanation: optional<string>

  obligations: PolicyObligations

  policy_revision: string
  evaluated_at: timestamp
}
```

A policy decision is immutable.

A new evaluation creates a new decision record.

---

## 3. `PolicyObligations`

```text
PolicyObligations {
  require_verification: boolean
  max_automatic_execution_attempts: optional<integer>
  max_automatic_recovery_attempts: optional<integer>
  automatic_compensation_allowed: boolean
  operator_reason_required: boolean
  approval_expires_at: optional<timestamp>
}
```

The initial obligation set is intentionally small.

New obligations that change runtime guarantees are contract changes.

Numeric defaults belong to configuration/policy, not this contract.

---

## 4. Policy inputs

Policy may consider canonical facts such as:

- requester identity/type;
- provider;
- effect action/version;
- risk level;
- material intent metadata;
- environment/deployment context;
- provider capability semantics;
- operation history if reevaluating;
- organization/deployment policy configuration.

Policy MUST NOT make provider mutation calls.

Policy output must be explainable enough to audit why an operation was allowed, denied, or gated.

---

## 5. Determinism

Given:

- equivalent policy configuration/revision;
- equivalent canonical policy input;

policy evaluation SHOULD return the same verdict/obligations.

If policy later incorporates nondeterministic external signals, those signals must be captured as durable policy input evidence.

An LLM may not be the sole authoritative policy decision-maker in v1.

---

## 6. Approval request

A `REQUIRE_APPROVAL` verdict creates or authorizes creation of an approval request.

```text
Approval {
  contract_version: "v1"
  approval_id: opaque_id
  operation_id: opaque_id
  operation_version: integer
  intent_digest: string
  policy_decision_id: opaque_id

  state: ApprovalState
  requested_at: timestamp
  expires_at: optional<timestamp>

  decided_at: optional<timestamp>
  decided_by: optional<PrincipalRef>
  reason: optional<string>
}
```

Canonical `ApprovalState`:

```text
PENDING
APPROVED
REJECTED
EXPIRED
CANCELLED
```

---

## 7. Approval binding

Approval is valid only for the exact material intent and control context it authorizes.

Before using `APPROVED`, Stateback MUST validate:

```text
approval.operation_id == operation.operation_id
approval.intent_digest == operation.intent.intent_digest
approval.operation_version is compatible with current version
approval.policy_decision_id == current applicable policy decision
approval not expired
approver authorized
operation.state == AWAITING_APPROVAL
```

A changed intent requires a new policy/approval path.

---

## 8. TOCTOU rule

Stateback must prevent:

```text
human approves intent A
        |
intent silently changes to B
        |
provider executes B
```

The binding digest/version check is mandatory at transition from `AWAITING_APPROVAL` to `READY`.

---

## 9. Approval does not execute

Approving an operation may cause a canonical transition and enqueue work.

The approval handler MUST NOT directly call a provider.

Provider execution occurs through the ordinary runtime path after durable state is `READY`.

---

## 10. Rejection and expiry

- `REJECTED` normally moves parent operation to `DENIED`.
- `EXPIRED` normally moves parent operation to `CANCELLED`.
- `CANCELLED` approval normally moves parent operation to `CANCELLED`.

Exact transition validity is owned by `STATE_MACHINES.md`.

---

## 11. Operator override

There is no generic "force execute" policy bypass in v1.

If a privileged operator needs to alter disposition:

- action must be explicitly supported by the state machine;
- authorization must be checked;
- reason must be captured;
- action must be audited;
- provider execution still uses canonical attempt/evidence semantics.

---

## 12. Policy failure

If policy evaluation fails because its deterministic dependencies are unavailable:

- provider execution is not allowed;
- operation remains or returns to a non-executable control state consistent with implementation;
- failure is auditable;
- fail-open is prohibited for consequential effects unless a future explicit policy decision establishes it.

---

## 13. Tests

Implementations must test:

- allow;
- deny;
- require approval;
- stale operation version;
- mismatched intent digest;
- wrong policy decision;
- unauthorized approver;
- expired approval;
- duplicate approval submission;
- concurrent approve/reject race;
- material intent change invalidates approval;
- approval cannot directly bypass `READY`.
