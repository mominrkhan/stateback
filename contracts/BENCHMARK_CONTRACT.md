# Stateback Benchmark Evidence Contract v1

**Status:** Canonical
**Version:** `sb-bench-v1`
**Owns:** benchmark methodology and provenance

## Correctness harness

Scenarios are deterministic pytest cases tagged `benchmark_correctness`. Each
asserts the final canonical PostgreSQL state and material audit evidence; cases
with a provider simulator also assert final external state. Existing crash and
concurrency assertions are reused, not weakened or copied into less strict
substitutes.

The catalog covers applicable crash-before-call, lost-response, duplicate work,
redelivery, worker/NATS/PostgreSQL interruption, provider timeout/unknown,
verification/compensation failure, concurrent workers, stale messages, API
idempotency, malicious MCP input, audit query determinism, and frontend state
behavior.

## Performance harness

The default runner performs 5 warmups and 30 measured repetitions per case,
records every raw monotonic nanosecond sample, and reports median and nearest-rank
p95. The default deterministic seed is `1709`. Failures remain in provenance and
must not be discarded from summary interpretation.

Cases state whether they are component or end-to-end measurements. End-to-end
cases cannot bypass authentication, application service, policy, journal, or
other production semantics.

## Required JSON provenance

```text
benchmark_version, stateback_commit_sha, workload, configuration, seed,
warmups, repetitions, aggregation, environment, python_version,
dependency_versions, postgres_version, nats_version, raw_measurements_ns,
failures, exclusions, summary
```

When a review run includes uncommitted task changes, it also records a
deterministic `source_tree_sha256` over the implementation, tests, harness,
frontend sources/locks, task, and governing benchmark/public contracts. A final
committed publication run still records both commit SHA and source digest.

Unavailable infrastructure versions are explicitly null only for runs that do
not use that infrastructure. Published/reviewed output must be reproducible from
the recorded workload and configuration.
