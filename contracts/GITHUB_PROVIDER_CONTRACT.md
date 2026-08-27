# GitHub Provider Contract

**Status:** Canonical Phase 10 v1
**Owns:** Stateback's first GitHub effect, its capability declaration, evidence rules, error normalization, and compensation limits.

## 1. Selection and effect

GitHub is the first real provider by explicit human decision for SB-008 on 2026-08-17.

The initial production-shaped effect is:

```text
EffectRef {
  provider: "github"
  action: "create_issue"
  version: "v1"
}
```

The effect creates an issue with caller-supplied `owner`, `repo`, `title`, optional `body`, optional labels, and optional assignees.

It does not create pull requests even though GitHub's issue listing/search representations may include pull requests.

## 2. Provider capability declaration

| Capability | v1 declaration | Basis |
|---|---|---|
| Mutability | `MUTATING` | Creates an externally visible repository issue |
| Risk | `MODERATE` | Consequential repository mutation, without code/deployment mutation |
| Idempotency | `NONE` | GitHub's create-issue REST endpoint does not expose a provider idempotency key |
| Verification | `CUSTOM` | Stateback marker search or direct issue read-back |
| Compensation | `MITIGATING` | Closing the issue reduces its active effect but does not erase history or recreate the pre-effect world |
| External identity | Supported | GitHub issue database ID and `owner/repo#number` are persisted |
| Immediate `APPLIED` proof | Supported | A well-formed HTTP 201 issue representation |
| Immediate `NOT_APPLIED` proof | Conditional | Conclusive HTTP rejection such as authentication, authorization, or validation rejection |

Stateback MUST NOT generate or send a fake GitHub idempotency header and MUST NOT describe issue creation as exactly-once.

GitHub's official create/update issue contract and fine-grained permission requirement are documented at:

- <https://docs.github.com/en/rest/issues/issues#create-an-issue>
- <https://docs.github.com/en/rest/issues/issues#update-an-issue>

## 3. Durable operation marker

Before POST, the adapter appends this non-secret marker to the issue body:

```text
<!-- stateback-operation:{operation_id} -->
```

The stable Stateback operation ID is already durable before provider invocation. The marker is provider-specific request metadata and does not become lifecycle authority.

The marker supports positive verification after response loss. It does not make the POST idempotent.

## 4. Execution outcome mapping

- Well-formed HTTP `201` with issue ID, number, HTTPS URL, and state: `APPLIED`.
- Local validation or missing credential before network: `NOT_APPLIED`.
- HTTP `401`, authorization/rate-limit rejection, `400`, `410`, or `422`: `NOT_APPLIED` because GitHub returned a conclusive rejection response.
- HTTP `5xx`, transport timeout/reset, or other failure after transmission may have begun: `UNKNOWN`.
- HTTP `201` with malformed/inconsistent issue representation: `UNKNOWN` because the issue may have been created.

Provider response bodies are not copied into normalized errors or audit records. Only safe status, request ID, external IDs, retry timing, and bounded evidence fields are retained.

## 5. Verification and reconciliation

When `owner/repo#number` is known, verification reads that issue directly.

When the create response was lost and no external identity is known, verification uses GitHub issue search for the exact Stateback marker across repositories visible to the configured credential.

- Exact marker match in a well-formed issue: `APPLIED`.
- No marker observed: `UNKNOWN`, never `NOT_APPLIED`, because search can be eventually consistent, permission-limited, or incomplete.
- Transport, authentication, malformed, contradictory, or inaccessible evidence: `UNKNOWN`.

Verification is safe to repeat and never creates or updates an issue.

## 6. Compensation

Compensation PATCHes the known issue to `state: closed`.

- Well-formed response showing `closed`: compensation outcome `APPLIED`.
- Conclusive rejection: compensation outcome `NOT_APPLIED`.
- Transport/5xx/malformed response after possible acceptance: compensation outcome `UNKNOWN` and requires verification.
- Compensation verification reads the issue: `closed` proves compensation `APPLIED`; `open` proves compensation `NOT_APPLIED`; inaccessible or inconsistent evidence remains `UNKNOWN`.

Closing is `MITIGATING`, not exact rollback: the issue and its history remain externally visible and a user may reopen it.

## 7. Credentials and sandbox

Production transport requires HTTPS and sends credentials only in the GitHub authorization header. Tokens, response bodies, and authorization headers MUST NOT enter Stateback evidence, errors, logs, audit, fixtures, or source control.

The minimum initial sandbox permission is a fine-grained credential scoped to the isolated repository with **Issues: write**. Broader repository or organization scopes are not required by this adapter.

Live tests require all of:

- `STATEBACK_RUN_GITHUB_SANDBOX=1`;
- `STATEBACK_GITHUB_SANDBOX_CONFIRM_MUTATION=1`;
- an isolated sandbox owner/repository;
- a manually supplied ephemeral token.

The sandbox test creates an issue and then closes it. It MUST NOT target a production repository.

## 8. Required evidence

- capability and registry contract tests;
- local validation and credential absence;
- successful external identity capture;
- conclusive provider rejection;
- rate-limit normalization and retry timing;
- transport timeout and HTTP 5xx ambiguity;
- malformed success ambiguity;
- positive marker verification and inconclusive absence;
- mitigating close and compensation read-back;
- cross-phase runtime test through policy/approval, outbox work, execution, `UNKNOWN`, and verification;
- opt-in isolated GitHub sandbox test.
