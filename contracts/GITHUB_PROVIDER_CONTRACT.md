# GitHub Provider Contract

**Status:** Canonical v1
**Owns:** supported GitHub effects, capability declarations, evidence rules,
error normalization, verification, and compensation limits.

## Shared rules

Every effect is a real GitHub REST mutation performed only by a
provider-executing worker. The API, SDK, MCP process, operation intent,
evidence, errors, logs, and frontend never receive the GitHub credential.
Mutating transport failures, `5xx` responses, redirects, and malformed apparent
successes are `UNKNOWN` because GitHub may have applied the request. Conclusive
authentication, authorization, validation, and other documented pre-acceptance
rejections are `NOT_APPLIED`.

Stateback does not send a fabricated provider idempotency header. Creation
effects append the non-secret marker
`<!-- stateback-operation:{operation_id} -->`. Exact positive marker matches can
prove `APPLIED`; search/list absence is `UNKNOWN` whenever observation may be
eventually consistent, permission-limited, or incomplete. Verification is
read-only and safe to repeat.

Before each mutation, the started attempt durably records the non-secret target
identities needed for read-back: issue target, label, repository/head/base, or
pull request/expected head SHA as applicable. A worker crash or ambiguous HTTP
response cannot erase these targets.

Normalized evidence may retain the GitHub request ID, external database/resource
identity, repository, issue/comment/PR number, bounded provider status, and an
HTTPS GitHub reference. Response bodies, authorization headers, and credentials
are never retained.

## Supported effects

| Effect | Risk | Idempotency | Verification | Compensation | Default local policy |
|---|---|---|---|---|---|
| `github.create_issue.v1` | `MODERATE` | `NONE` | `CUSTOM` marker search/direct read | `MITIGATING` close | approval |
| `github.create_issue_comment.v1` | `MODERATE` | `NONE` | `CUSTOM` marker direct/list read | `NONE` | approval |
| `github.add_label.v1` | `LOW` | `NATURAL` state convergence | `READ_BACK` issue labels | `NONE` | approval |
| `github.create_pull_request.v1` | `MODERATE` | `NONE` | `CUSTOM` marker plus head/base/direct read | `MITIGATING` close | approval |
| `github.merge_pull_request.v1` | `HIGH` | `NONE` | `READ_BACK` exact PR and expected head | `NONE` | approval |

Unmatched effects remain denied. Submission acceptance, including through MCP,
does not prove provider application.

## Create issue

Arguments are `owner`, `repo`, `title`, optional `body`, optional string arrays
`labels` and `assignees`. A well-formed `201` issue identity is
`APPLIED`. Verification reads a known issue or searches for the exact marker.
Closing a known issue is mitigating because history and prior observation
remain; it is not rollback.

## Create issue comment

Arguments are `owner`, `repo`, positive `issue_number`, and `body`. The marker
is appended to the comment body. A well-formed `201` comment identity is
`APPLIED`. Verification reads a known comment or lists the target issue's
comments and accepts only an exact marker match. Bounded-list absence is
`UNKNOWN`. Comment deletion is not exposed as compensation.

## Add label

Arguments are `owner`, `repo`, positive `issue_number`, and one non-empty
`label`. GitHub's add-label operation converges on the label being present;
repeating the same addition does not create another label, so the effect is
declared `NATURAL`. A well-formed `200` label list containing the intended label
is `APPLIED`. Read-back presence is `APPLIED`; read-back absence is
`NOT_APPLIED` for the intended current-state effect. Stateback does not remove
the label as compensation because it may have existed before this operation.

## Create pull request

Arguments are `owner`, `repo`, `head`, `base`, `title`, optional `body`, and
optional `draft`. The marker is appended to the PR body. A well-formed `201` PR
identity whose returned head and base match the submitted intent is `APPLIED`.
Identity or head/base inconsistency is `UNKNOWN`. Verification reads a known PR
or lists the intended repository/head/base and requires both the exact marker
and exact head/base. List absence is `UNKNOWN`.
Closing a known PR is mitigating, not rollback.

## Merge pull request

Arguments are `owner`, `repo`, positive `pull_number`, a 40-hex `head_sha`, and
optional `merge_method` from `merge`, `squash`, or `rebase`. Stateback sends the
expected SHA through GitHub's merge endpoint so a changed head cannot silently
reuse approval for older intent. Only a well-formed `200` response with
`merged: true` and a well-formed 40-hex merge SHA is immediately `APPLIED`.
GitHub's documented `405` cannot-merge and `409` expected-SHA mismatch responses,
or a well-formed `200` with `merged: false`, establish `NOT_APPLIED`.

Verification reads the exact PR. It returns `APPLIED` only when the PR is merged
and the observed head equals the approved expected SHA. The `merged` field must
be an actual boolean. An unchanged expected head with `merged: false` is
`NOT_APPLIED`; a changed head, inaccessible state,
transport failure, or malformed evidence is `UNKNOWN`. A merge cannot be
generically unmerged, so compensation is `NONE`.

## Local UNKNOWN demonstration

The normal production worker has no fault-injection facility. The private local
development worker may wrap this adapter with a one-shot arm stored in its
private run directory and named by one exact operation ID. Only after that
operation's create-issue call returns `APPLIED` does the wrapper consume the arm
and discard usable success evidence, producing `UNKNOWN`. Normal marker
verification then owns reconciliation. Wrong IDs, non-regular arm paths,
pre-mutation failures, and subsequent operations are unaffected. There is no
HTTP fault endpoint or policy bypass.

## Sandbox

Normal CI uses deterministic transports. Real GitHub tests require the existing
explicit sandbox confirmation and an isolated repository. Merge testing also
requires `STATEBACK_GITHUB_SANDBOX_CONFIRM_MERGE=1`; no ordinary CI job mutates
GitHub.
