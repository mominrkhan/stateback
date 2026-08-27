# Guarantees and limitations

Stateback guarantees only what its durable records, provider capabilities, and
evidence can establish:

- durable intent precedes consequential execution;
- PostgreSQL is authoritative for Stateback lifecycle state;
- JetStream coordinates work and is not lifecycle truth;
- ambiguous provider outcomes remain `UNKNOWN` until evidence resolves them;
- retries require an explicit idempotency, deduplication, or verification
  basis;
- policy precedes execution and approval is bound to immutable intent;
- compensation is a separate effect with its own outcome and evidence; and
- operator actions are authorized, attributable, version-checked, and audited.

Stateback does not claim universal exactly-once execution across arbitrary
providers, distributed ACID transactions over external APIs, or exact rollback.
The GitHub `create_issue/v1` effect has no provider idempotency key. A lost
response can therefore require marker-based verification, and absence from
GitHub search is not proof that the issue was not created. Closing an issue is
mitigation, not erasure of history or restoration of the prior world.

Semantic summaries are optional advisory interpretations. They never authorize
an action, change operation state, resolve an unknown outcome, or replace
provider evidence.
