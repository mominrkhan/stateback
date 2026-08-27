# Stateback Canonical Contracts

**Status:** Canonical contract index

These files define machine-facing semantics. They are normative even before concrete Python/database/API types are implemented.

The implementation may choose private class names and table layouts, but it MUST preserve these meanings.

## Contract files

- `enums-v1.md` — exact v1 enum and wire symbols, initialization constants,
  terminal-state sets, and stable Stateback identity formats.
- `OPERATION_CONTRACT.md` — operation identity, intent, lifecycle aggregate, attempts.
- `PROVIDER_ADAPTER_CONTRACT.md` — capabilities, execution boundary, evidence normalization.
- `POLICY_CONTRACT.md` — policy verdicts, obligations, approvals.
- `VERIFICATION_CONTRACT.md` — verification/reconciliation evidence.
- `COMPENSATION_CONTRACT.md` — compensation semantics and lifecycle.
- `MESSAGING_CONTRACT.md` — outbox and JetStream work-message semantics.
- `AUDIT_CONTRACT.md` — append-only audit event model.
- `ERROR_CONTRACT.md` — normalized errors and their relationship to effect outcome.
- `SEMANTIC_ASSISTANCE_CONTRACT.md` — optional advisory operator audit summaries.

## Normative type notation

Pseudo-types in these contracts are language-neutral:

```text
string
integer
boolean
timestamp
json
map<string, string>
optional<T>
list<T>
enum<A | B | C>
```

An `opaque_id` is a globally unique immutable identifier. The concrete encoding (UUIDv7 or another scheme) is an implementation detail unless a public contract later fixes it.

## Compatibility

A persisted or public contract change is breaking if it:

- changes the meaning of an existing field;
- removes a field required by readers;
- changes enum semantics;
- makes previously valid persisted data invalid;
- changes idempotency or lifecycle meaning;
- changes an event meaning without versioning.

Additive optional fields are generally compatible if old readers can safely ignore them.

## Public/product surface contracts

- `AUTH_CONTRACT.md` owns authenticated identity, roles, and permissions.
- `PUBLIC_API_CONTRACT.md` owns HTTP, SDK, MCP, pagination, and compatibility semantics.
- `OPERATOR_CONTRACT.md` owns operator reconstruction and legal control surfaces.
- `BENCHMARK_CONTRACT.md` owns correctness/performance methodology and provenance.
- `SEMANTIC_ASSISTANCE_CONTRACT.md` owns the Phase 16 operator summary surface.

## Serialization

Implementations MUST:

- serialize enum values exactly as canonical symbols unless a versioned public mapping is defined;
- use UTC timestamps;
- preserve opaque identifiers exactly;
- avoid serializing secrets;
- reject unknown required contract versions rather than guessing.

## Versioning

Each public/message contract has a version.

Initial canonical version is `v1`.

Internal persisted schemas may use database migrations rather than embedding a version in every row, but public and messaging schemas MUST have explicit version semantics.

## Evidence principle

Contracts separate:

- operation state;
- effect outcome;
- normalized error;
- provider evidence.

Do not collapse these into one success/error field.

## Source-of-truth principle

Contract instances stored in PostgreSQL are authoritative for Stateback knowledge. Provider state remains external truth for provider resources.
