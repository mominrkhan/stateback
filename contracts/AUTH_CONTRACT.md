# Stateback Authentication and Authorization Contract v1

**Status:** Canonical
**Version:** `v1`
**Owns:** caller authentication result, roles, and public/operator permissions

## Authentication boundary

A deployment-supplied authenticator receives transport credentials and returns
either an authenticated identity or a normalized authentication failure. An
identity contains exactly:

```text
principal: PrincipalRef
roles: set[CALLER | READER | OPERATOR | APPROVER]
```

Request bodies and MCP arguments MUST NOT select or override the authenticated
principal. Credentials, tokens, and authenticator diagnostics MUST NOT enter
operation intent, audit data, API errors, logs, frontend bundles, or benchmark
artifacts.

## Permissions

| Action | Required role |
|---|---|
| submit a managed operation | `CALLER` |
| read own operation/status/history | `CALLER` or `READER` |
| search/reconstruct operations | `OPERATOR` |
| request verification/recovery/compensation | `OPERATOR` |
| approve or reject a pending approval | `APPROVER` |

Deployments MAY further restrict reads and actions. They MUST NOT grant an action
that canonical state/policy rules reject.

## Failure behavior

- Missing/invalid credentials: authentication failure; no operation is created.
- Authenticated but insufficient role: authorization failure; no action occurs.
- Authenticator unavailable: transport/infrastructure failure; no operation is
  created or changed.
- Approval proves authorization for one bound intent; it does not authenticate
  the approver.

Every accepted privileged operator action records the authenticated principal.
Rejected privileged actions are safe to audit only with redacted data.
