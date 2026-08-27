# Stateback Operator Query and Control Contract v1

**Status:** Canonical
**Version:** `v1`
**Owns:** operator reconstruction, search, and control surface semantics

## Query

`GET /v1/operator/operations` requires `OPERATOR`, orders by
`(created_at DESC, operation_id ASC)`, and supports exact state/provider plus
inclusive UTC time filters. Cursor pagination carries the last ordering tuple;
limit is 1–100, default 50.

`GET /v1/operator/operations/{operation_id}` reconstructs authoritative state
from PostgreSQL records and returns operation intent/classification, policy
decisions, approvals, execution attempts, provider identities/evidence,
verification and reconciliation history, compensation and its attempts, audit
timeline, canonical state/version, timestamps, and correlation identifiers.
Absent categories are empty/null, never fabricated from logs.
The reconstruction includes `available_actions`, computed by the backend from
current state, provider capabilities, policy, and durable evidence. Clients
must not infer control eligibility from lifecycle state alone.

All query output passes canonical secret rejection/redaction rules.

`POST /v1/operator/operations/{operation_id}/semantic-summary` is the optional,
read-only advisory surface defined by `SEMANTIC_ASSISTANCE_CONTRACT.md`. It does
not add an available action or mutate the operation/audit history.

## Controls

The v1 controls are:

- approve or reject the current pending approval (`APPROVER`);
- request supported verification from `MANUAL_INTERVENTION` (`OPERATOR`);
- start supported compensation (`OPERATOR`);
- retry failed compensation through the canonical compensation service
  (`OPERATOR`);
- escalate through canonical recovery/compensation services (`OPERATOR`).

Every command carries the expected operation version, authenticated actor,
reason, and correlation ID. Stale/illegal commands return conflict and make no
change. There is no force-success, state assignment, or unconditional retry.

Accepted controls record append-only operator audit evidence through the
canonical transition/service path. Frontend confirmation is usability defense;
server authorization and state/version checks remain mandatory.
