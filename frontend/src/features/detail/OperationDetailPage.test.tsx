import { render, screen, within } from "@testing-library/react";

import { parseReconstruction } from "../../api/parsers";
import type { ProviderEvidence, Reconstruction } from "../../api/types";
import emptyFixture from "../../test/contract-fixtures/reconstruction-empty-verifications-v1.json";
import verificationFixture from "../../test/contract-fixtures/reconstruction-verification-v1.json";
import { OperationDetailPage } from "./OperationDetailPage";
import { outcomeSummary } from "./OutcomeExplanation";

const base = parseReconstruction(emptyFixture);
const evidence: ProviderEvidence = {
  source: "provider_response",
  provider: "github",
  observed_at: "2026-08-20T12:01:00Z",
  provider_status: "created",
  provider_request_id: "request-safe-1",
  external_operation_id: "external-operation-1",
  external_resource_ids: ["issue-42"],
  evidence_fields: { secret_provider_body: "must-not-render" },
  raw_reference: null,
};

const reconstruction: Reconstruction = {
  ...base,
  operation: {
    ...base.operation,
    state: "UNKNOWN",
    intent: {
      ...base.operation.intent,
      arguments: {
        owner: "octo-org",
        repo: "stateback",
        title: "Durable issue",
        labels: ["safety", "agent"],
        assignees: ["operator"],
        body: "secret body",
        unknown_argument: "must-not-render",
      },
    },
    latest_attempt_id: "attempt-1",
    compensation_id: "compensation-1",
    updated_at: "2026-08-20T12:05:00Z",
  },
  policy_decisions: [{
    contract_version: "v1",
    policy_decision_id: "policy-1",
    operation_id: base.operation.operation_id,
    operation_version: 2,
    intent_digest: base.operation.intent.intent_digest,
    verdict: "ALLOW",
    reason_codes: ["policy_allowed"],
    explanation: "Accepted by policy.",
    obligations: {
      require_verification: true,
      max_automatic_execution_attempts: 1,
      max_automatic_recovery_attempts: 1,
      automatic_compensation_allowed: false,
      operator_reason_required: true,
      approval_expires_at: null,
    },
    policy_revision: "revision-1",
    evaluated_at: "2026-08-20T12:00:10Z",
  }],
  approvals: [{
    contract_version: "v1",
    approval_id: "approval-1",
    operation_id: base.operation.operation_id,
    operation_version: 2,
    intent_digest: base.operation.intent.intent_digest,
    policy_decision_id: "policy-1",
    state: "APPROVED",
    requested_at: "2026-08-20T12:00:20Z",
    expires_at: null,
    decided_at: "2026-08-20T12:00:30Z",
    decided_by: { type: "OPERATOR", id: "operator-1", display_name: "Operator One" },
    reason: "Reviewed",
  }],
  attempts: [{
    contract_version: "v1",
    attempt_id: "attempt-1",
    operation_id: base.operation.operation_id,
    attempt_number: 1,
    state: "COMPLETED",
    started_at: "2026-08-20T12:00:40Z",
    completed_at: "2026-08-20T12:01:00Z",
    provider_idempotency_key: "provider-secret-key",
    external_operation_id: "external-operation-1",
    external_resource_ids: ["issue-42"],
    outcome: "UNKNOWN",
    evidence,
    error: {
      contract_version: "v1",
      kind: "TRANSPORT",
      code: "response_lost",
      message: "Provider response was lost.",
      retryable_infrastructure: false,
      provider_http_status: null,
      provider_error_code: null,
      retry_after_seconds: null,
      details: { hidden: "error-details-secret" },
    },
    correlation_id: "correlation-1",
  }],
  reconciliations: [{
    reconciliation_decision_id: "reconciliation-1",
    operation_id: base.operation.operation_id,
    operation_version: 2,
    verification_id: null,
    decision: { action: "MANUAL_REVIEW", reason_code: "verification_unavailable" },
    created_at: "2026-08-20T12:02:00Z",
  }],
  compensation: {
    contract_version: "v1",
    compensation_id: "compensation-1",
    original_operation_id: base.operation.operation_id,
    kind: "BEST_EFFORT",
    state: "PENDING",
    version: 1,
    intent_digest: "compensation-digest",
    arguments_mode: "INLINE",
    arguments: { hidden_compensation_argument: "must-not-render" },
    arguments_ref: null,
    idempotency_identity: "compensation-idempotency",
    requested_by: { type: "OPERATOR", id: "operator-1", display_name: "Operator One" },
    policy_decision_id: null,
    created_at: "2026-08-20T12:03:00Z",
    updated_at: "2026-08-20T12:03:00Z",
  },
  compensation_attempts: [{
    contract_version: "v1",
    compensation_attempt_id: "compensation-attempt-1",
    compensation_id: "compensation-1",
    attempt_number: 1,
    state: "COMPLETED",
    started_at: "2026-08-20T12:03:10Z",
    completed_at: "2026-08-20T12:03:20Z",
    provider_idempotency_key: "compensation-provider-secret",
    external_operation_id: "compensation-external-1",
    outcome: "APPLIED",
    evidence,
    error: null,
  }],
  audit: [
    {
      contract_version: "v1",
      audit_event_id: "audit-second-sequence-number",
      operation_id: base.operation.operation_id,
      sequence: 8,
      event_type: "execution.evidence_recorded.v1",
      from_state: "EXECUTING",
      to_state: "UNKNOWN",
      operation_version: 2,
      actor: null,
      reason_code: "provider_outcome_unknown",
      data: { hidden_audit_data: "must-not-render" },
      correlation_id: "correlation-1",
      created_at: "2026-08-20T12:01:00Z",
    },
    {
      contract_version: "v1",
      audit_event_id: "audit-first-sequence-number",
      operation_id: base.operation.operation_id,
      sequence: 3,
      event_type: "approval.decided.v1",
      from_state: "AWAITING_APPROVAL",
      to_state: "READY",
      operation_version: 1,
      actor: { type: "OPERATOR", id: "operator-1", display_name: "Operator One" },
      reason_code: "approved",
      data: {},
      correlation_id: "correlation-2",
      created_at: "2026-08-20T12:00:30Z",
    },
  ],
  available_actions: ["verify"],
};

test("renders the complete reconstruction hierarchy and integration slots", () => {
  render(
    <OperationDetailPage
      reconstruction={reconstruction}
      actions={<button type="button">Request verification</button>}
      advisory={<aside>Advisory summary slot</aside>}
    />,
  );
  expect(screen.getByRole("heading", { name: "Create issue with GitHub" })).toBeVisible();
  expect(screen.getAllByText("Outcome unknown").find((node) => node.classList.contains("state-badge"))).toHaveClass("state-badge--unresolved");
  expect(screen.getByText("github.create_issue.v1")).toBeInTheDocument();
  expect(screen.getAllByText(/Fixture Agent — AGENT: fixture-agent/)).toHaveLength(2);
  expect(screen.getByText(/2026-08-20T12:05:00.000Z UTC/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Request verification" })).toBeVisible();
  expect(screen.getByText("Advisory summary slot")).toBeVisible();
  for (const heading of ["Summary", "Evidence", "Execution attempts", "Verification and reconciliation", "Compensation", "Durable audit"]) {
    expect(screen.getByRole("heading", { name: heading })).toBeVisible();
  }
});

test("keeps human status and controls ahead of subordinate technical details", () => {
  render(<OperationDetailPage reconstruction={reconstruction} actions={<button type="button">Request verification</button>} />);
  const critical = screen.getByLabelText("Critical operation status and controls");
  expect(within(critical).getByText("Outcome unknown")).toHaveClass("state-badge--unresolved");
  expect(within(critical).getByRole("button", { name: "Request verification" })).toBeVisible();
  expect(within(critical).queryByText("Requester")).not.toBeInTheDocument();
  expect(screen.getByText("Requester")).toBeVisible();
  expect(screen.getByText("Technical details")).toBeVisible();
  expect(screen.getByLabelText(`operation ID: ${reconstruction.operation.operation_id}`)).toBeInTheDocument();
});

test("shows only the GitHub create-issue approval allowlist and body counts", () => {
  render(<OperationDetailPage reconstruction={reconstruction} />);
  expect(screen.getByText("octo-org")).toBeVisible();
  expect(screen.getByText("stateback")).toBeVisible();
  expect(screen.getAllByText("Durable issue").length).toBeGreaterThan(0);
  expect(screen.getByText("safety, agent")).toBeVisible();
  expect(screen.getByText("operator")).toBeVisible();
  expect(screen.getByText("11 characters / 11 bytes; content withheld")).toBeVisible();
  for (const secret of ["secret body", "must-not-render", "provider-secret-key", "error-details-secret", "compensation-provider-secret"]) {
    expect(screen.queryByText(secret)).not.toBeInTheDocument();
  }
});

test("renders the head-bound GitHub merge summary without raw unknown arguments", () => {
  const merge: Reconstruction = {
    ...base,
    operation: {
      ...base.operation,
      risk_level: "HIGH",
      intent: {
        ...base.operation.intent,
        effect: { provider: "github", action: "merge_pull_request", version: "v1" },
        arguments: {
          owner: "octo-org",
          repo: "stateback",
          pull_number: 123,
          head_sha: "abcdef1234567890abcdef1234567890abcdef12",
          merge_method: "squash",
          hidden_provider_option: "must-not-render",
        },
      },
    },
  };

  render(<OperationDetailPage reconstruction={merge} />);

  expect(screen.getByRole("heading", { name: "Merge pull request with GitHub" })).toBeVisible();
  expect(screen.getByText("#123")).toBeVisible();
  expect(screen.getByText("abcdef1234567890abcdef1234567890abcdef12")).toBeVisible();
  expect(screen.getByText("squash")).toBeVisible();
  expect(screen.queryByText("must-not-render")).not.toBeInTheDocument();
});

test("keeps provider evidence, attempt outcome, reconciliation, and compensation distinct", () => {
  render(<OperationDetailPage reconstruction={reconstruction} />);
  expect(screen.getByRole("heading", { name: "Execution attempt 1: authoritative provider evidence" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "Compensation attempt 1: authoritative provider evidence" })).toBeVisible();
  expect(screen.getAllByText("Provider evidence is distinct from verification and canonical operation state.")).toHaveLength(2);
  expect(screen.getByText("Provider outcome").nextElementSibling).toHaveTextContent("UNKNOWN");
  expect(screen.getByText("MANUAL_REVIEW: verification_unavailable")).toBeVisible();
  expect(screen.getByText("No verification record is present.")).toBeVisible();
  expect(screen.getByText("BEST_EFFORT")).toBeVisible();
  expect(screen.getByText(/Compensation is a separate side effect/)).toBeVisible();
});

test("renders non-empty verification history without inferring canonical state", () => {
  const withVerification: Reconstruction = parseReconstruction(verificationFixture);
  render(<OperationDetailPage reconstruction={withVerification} />);
  expect(screen.getByLabelText("verification ID: 00000000-0000-4000-8000-000000000002")).toBeVisible();
  expect(screen.getByText("ORIGINAL_EFFECT: github / create_issue / v1")).toBeVisible();
  expect(screen.getByText("Outcome: APPLIED")).toBeVisible();
  expect(screen.getByText("Evidence: github — found")).toBeVisible();
  expect(screen.queryByText("Verification records are not available")).not.toBeInTheDocument();
});

test("renders every audit event in backend order with durable IDs, actor, and correlations", () => {
  render(<OperationDetailPage reconstruction={reconstruction} />);
  const timeline = screen.getByRole("heading", { name: "Durable audit" }).parentElement!;
  const entries = within(timeline).getAllByRole("listitem");
  expect(entries).toHaveLength(2);
  expect(entries[0]).toHaveTextContent("Sequence 8: execution.evidence_recorded.v1");
  expect(entries[0]).toHaveTextContent("audit-second-sequence-number");
  expect(entries[0]).toHaveTextContent("correlation-1");
  expect(entries[1]).toHaveTextContent("Sequence 3: approval.decided.v1");
  expect(entries[1]).toHaveTextContent("Operator One — OPERATOR: operator-1");
  expect(entries[1]).toHaveTextContent("correlation-2");
});

test("omits all arguments for effects without an accepted display policy", () => {
  const generic: Reconstruction = {
    ...base,
    operation: {
      ...base.operation,
      intent: {
        ...base.operation.intent,
        effect: { provider: "future-provider", action: "future-action", version: "v1" },
        arguments: { dangerous_unknown: "never-render-generic-value" },
      },
    },
  };
  render(<OperationDetailPage reconstruction={generic} />);
  expect(screen.getByRole("heading", { name: "Unsupported effect with Unsupported provider" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "GitHub issue review" })).not.toBeInTheDocument();
  expect(screen.queryByText("never-render-generic-value")).not.toBeInTheDocument();
  expect(screen.getByText("future-provider.future-action.v1")).toBeInTheDocument();
});

test("explains UNKNOWN without failure or unsafe retry wording", () => {
  render(<OperationDetailPage reconstruction={reconstruction} />);
  expect(screen.getByText("This does not mean the operation failed.")).toBeVisible();
  expect(screen.getByText("Stateback will not blindly retry the action.")).toBeVisible();
  expect(screen.queryByRole("button", { name: /try again|retry failed operation/i })).not.toBeInTheDocument();
});

test("orders the human lifecycle by durable sequence while preserving raw audit order", () => {
  render(<OperationDetailPage reconstruction={reconstruction} />);
  const lifecycle = screen.getByRole("heading", { name: "Lifecycle" }).closest("section")!;
  const entries = within(lifecycle).getAllByRole("listitem");
  expect(entries[0]).toHaveTextContent("Approval granted");
  expect(entries[1]).toHaveTextContent("Provider outcome became uncertain");
  const raw = screen.getByRole("heading", { name: "Durable audit" }).parentElement!;
  expect(within(raw).getAllByRole("listitem")[0]).toHaveTextContent("Sequence 8");
});

test("explains active verification and compensation uncertainty without treating either as failure", () => {
  const verifying: Reconstruction = {
    ...reconstruction,
    operation: { ...reconstruction.operation, state: "VERIFYING" },
  };
  const compensationUnknown: Reconstruction = {
    ...reconstruction,
    operation: { ...reconstruction.operation, state: "COMPENSATION_UNKNOWN" },
  };
  const { rerender } = render(<OperationDetailPage reconstruction={verifying} />);
  expect(screen.getByRole("heading", { name: "Verifying external outcome" })).toBeVisible();
  expect(screen.getAllByText(/checking the provider for evidence/).length).toBeGreaterThan(0);
  rerender(<OperationDetailPage reconstruction={compensationUnknown} />);
  expect(screen.getByRole("heading", { name: "Compensation outcome unknown" })).toBeVisible();
  expect(screen.getByText(/cannot yet prove whether it was applied/)).toBeVisible();
});

test("describes reconciliation-backed terminal outcomes only from durable decisions", () => {
  const succeeded: Reconstruction = {
    ...reconstruction,
    operation: { ...reconstruction.operation, state: "SUCCEEDED" },
    reconciliations: [{
      ...reconstruction.reconciliations[0],
      decision: { action: "MARK_SUCCEEDED", reason_code: "verification_applied" },
    }],
  };
  const failed: Reconstruction = {
    ...reconstruction,
    operation: { ...reconstruction.operation, state: "FAILED" },
    reconciliations: [{
      ...reconstruction.reconciliations[0],
      decision: { action: "MARK_FAILED", reason_code: "verification_not_applied" },
    }],
  };
  expect(outcomeSummary(succeeded)).toMatch(/reconciled it to Succeeded without repeating it/);
  expect(outcomeSummary(failed)).toMatch(/Verification evidence established/);
});
