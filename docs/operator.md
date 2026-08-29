# Operator guide

Operator resources require the `OPERATOR` role. PostgreSQL reconstruction is
authoritative; logs, worker exits, JetStream acknowledgements, and UI state
must not be used as proof of an external result.

## Reconstruct and search

- `GET /v1/operator/overview` returns authoritative attention and active-state
  counts, the eight most recent operations, and configured provider capability
  metadata. It never returns provider credentials or calls a provider.
- `GET /v1/operator/operations` searches by exact state/provider and UTC time
  range with cursor pagination. `attention=true` selects the canonical
  attention-state set without introducing a new lifecycle state.
- `GET /v1/operator/operations/{operation_id}` reconstructs intent, policy,
  approval, attempts, provider evidence, verification, compensation, audit,
  and currently available actions.

Clients must use `available_actions`; they must not infer control eligibility
from a lifecycle state alone.

## Controls

The v1 control surface supports:

- approve or reject pending approval (`APPROVER`);
- request supported verification (`OPERATOR`);
- start or retry supported compensation (`OPERATOR`);
- escalate through the canonical recovery service (`OPERATOR`).

Every command includes the expected operation version, actor identity, reason,
and correlation ID. Stale or illegal commands are rejected; there is no
force-success, arbitrary state assignment, or unconditional retry.

## Optional semantic summary

`POST /v1/operator/operations/{operation_id}/semantic-summary` is a read-only,
advisory summary of the authorized audit timeline. It never authorizes an
action, resolves `UNKNOWN`, supplies provider evidence, or changes lifecycle
state. Local Ollama is optional; deterministic reconstruction and controls
remain usable without it.

See [guarantees](guarantees.md) and `contracts/OPERATOR_CONTRACT.md` before
taking a recovery action.
