# Stateback Product Specification

**Status:** Canonical
**Product:** Stateback
**Historical name:** AgentTX
**Positioning:** **Transactions for AI agents**

## 1. Product definition

Stateback is a transactional safety and recovery layer for autonomous AI agents that perform consequential external side effects.

Stateback owns the boundary:

```text
agent computation
      |
      v
Stateback effect boundary
      |
      v
external system / real world
```

Examples of consequential external systems include:

- SaaS APIs;
- source-control and developer tooling;
- deployment systems;
- production databases;
- infrastructure and cloud APIs;
- ticketing systems;
- internal operational APIs;
- financial or administrative systems;
- any system where a repeated, partially completed, or incorrectly recovered action can create real-world harm.

Stateback exists because an LLM retry is not equivalent to safely retrying an external action.

## 2. Core problem

Traditional application code often treats a call as:

```text
call function
    |
 success / exception
    |
 retry if needed
```

That model is unsafe at an external side-effect boundary.

A provider may apply an effect and then:

- the network response may be lost;
- the process may crash;
- the local database write may fail;
- the worker may be redelivered;
- the provider may return a malformed or inconsistent response.

In these cases, local failure does not prove external non-execution.

Stateback therefore manages:

- durable intent;
- stable operation identity;
- effect semantics;
- policy and approval;
- execution evidence;
- provider-native idempotency where available;
- verification and reconciliation;
- bounded, evidence-based retry;
- compensation;
- recovery;
- auditability.

## 3. Product wedge

Stateback is **not a generic durable workflow engine**.

Stateback does not attempt to replace systems whose primary concern is durable continuation of arbitrary computation, including systems in the category of Temporal, DBOS, Restate, LangGraph, or equivalent workflow/durable-execution runtimes.

Those systems primarily ask:

> How does computation continue reliably?

Stateback primarily asks:

> How does an autonomous agent safely cross from computation into a consequential external side effect when the result can be irreversible, duplicated, ambiguous, or only partially recoverable?

Stateback MAY be used alongside a durable workflow runtime.

Stateback MUST NOT drift into generic orchestration merely because workflow features are convenient to add.

## 4. Primary users

Initial primary users are developers and platform teams building agents with write access to real systems.

The initial orientation is deliberately developer/infrastructure-heavy, especially:

- coding agents;
- DevOps and SRE agents;
- repository automation;
- deployment and infrastructure agents;
- internal engineering automation;
- agents with write access to production SaaS or operational systems.

Other verticals such as support, sales/revenue operations, finance, and general business automation remain plausible, but they are not the first design center.

## 5. Product promise

Stateback should make the safe path easier than each application team independently rebuilding distributed-systems safety around every tool call.

A developer should be able to request a consequential operation while Stateback supplies structured support for:

```text
intent
policy
identity
execution
idempotency
durability
verification
reconciliation
recovery
compensation
auditability
```

The abstraction MUST remain honest about what the external provider actually permits.

## 6. Guarantees Stateback may provide

The exact guarantee is effect- and provider-dependent.

Stateback may provide combinations of:

- durable intent-before-effect;
- durable operation identity;
- serialized local lifecycle transitions;
- stable idempotency identity;
- at-least-once work delivery with operation-level deduplication;
- provider-native idempotent execution when supported;
- verification/reconciliation of ambiguous outcomes when supported;
- safe retry after evidence establishes it is legal;
- exact, approximate, or mitigating compensation when supported;
- explicit unresolved/manual-intervention state when automatic convergence cannot be proven;
- append-only audit reconstruction.

Stateback MUST describe guarantees precisely per provider/effect.

## 7. Guarantees Stateback does not claim

Stateback MUST NOT claim:

- universal exactly-once execution across arbitrary external APIs;
- universal ACID transactions across unrelated external systems;
- universal rollback;
- that every external side effect is reversible;
- that a timeout means the effect did not happen;
- that provider-reported success always equals externally verified state;
- that compensation erases history;
- that an LLM can determine external truth without evidence;
- that durable messaging itself makes external side effects exactly-once.

## 8. Effect semantics are part of the product

Stateback treats operations as effects with declared semantics rather than generic function calls.

At minimum, the system must be able to reason about:

- read-only versus mutating behavior;
- provider-native or natural idempotency;
- provider idempotency-key support;
- external operation identity;
- whether external state can be verified;
- how verification is performed;
- whether an effect has an exact inverse;
- whether only approximate/mitigating compensation exists;
- whether the effect is irreversible;
- whether a provider response can leave execution outcome unknown;
- whether human approval is required;
- whether automatic retry or compensation is permitted.

These semantics MUST be explicit at a canonical provider/effect boundary.

## 9. Core execution model

The intended conceptual flow is:

```text
request effect
      |
      v
durably record intent
      |
      v
classify effect + capabilities
      |
      v
policy / approval decision
      |
      v
establish stable execution + idempotency identity
      |
      v
record execution attempt before provider mutation
      |
      v
invoke provider
      |
      v
record provider evidence / external identity
      |
      +-----------------------------+
      |                             |
 conclusive                      uncertain
      |                             |
      v                             v
verify if required          verify / reconcile
      |                             |
      v                             v
succeed / fail            safe retry / converge /
                          compensate / escalate
```

The concrete legal states and transitions are owned by `STATE_MACHINES.md`.

## 10. Developer experience principles

Stateback's developer experience should:

1. make consequential effects explicit;
2. require less custom recovery code than unsafe direct tool calls;
3. expose the real guarantee instead of hiding uncertainty;
4. provide durable handles for operation status;
5. make audit and recovery information available without log archaeology;
6. keep provider-specific mechanics behind typed adapters;
7. allow applications to choose policy without rewriting execution semantics;
8. permit local/self-hosted development without mandatory paid infrastructure.

Developer convenience MUST NOT weaken correctness invariants.

## 11. Operator experience principles

An operator must eventually be able to answer:

- What did the agent intend to do?
- Which actor requested it?
- Which policy decision allowed or blocked it?
- Was approval required?
- Was the provider invoked?
- How many execution attempts occurred?
- Which idempotency identity was used?
- Did the provider return an external operation/resource identity?
- What evidence exists about the external outcome?
- Was verification performed?
- Was recovery attempted?
- Was compensation attempted?
- What is the current canonical state?
- Why is the operation unresolved, if it is unresolved?

This information should be reconstructible from authoritative state and audit history, not inferred from application logs.

## 12. Product non-goals

The initial product is not intended to be:

- a prompt framework;
- an agent planner;
- a generic task queue;
- a general workflow DSL;
- a replacement for every provider SDK;
- an LLM observability vendor;
- a distributed transaction coordinator that pretends arbitrary APIs support two-phase commit;
- an opaque "autonomy safety score";
- a hosted-only platform whose correctness depends on a proprietary control plane.

## 13. Initial success criteria

Stateback reaches a credible initial product state when it can demonstrate, with fault injection and real provider integrations, that:

1. an effect cannot normally execute without durable intent;
2. crash-after-provider-success does not cause blind replay;
3. duplicate worker delivery does not produce uncontrolled duplicate effects;
4. provider idempotency is used correctly when available;
5. unknown outcomes remain explicit and can reconcile when evidence is available;
6. compensation is represented honestly and survives its own failures;
7. policy/approval is auditable and bound to the exact approved intent;
8. operators can reconstruct what happened;
9. benchmark results preserve baseline integrity;
10. the core system is self-hostable and does not require a recurring paid service to operate correctly.

## 14. Product evolution rule

New features are appropriate when they strengthen transactional safety at the agent-to-world boundary.

Before adding a major feature, ask:

> Does this improve the correctness, control, recovery, evidence, or operability of consequential agent side effects?

If the answer is primarily "it makes Stateback a broader workflow platform," the feature is outside the current product wedge unless explicitly reconsidered.
