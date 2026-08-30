import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";

import type { OperatorClient } from "../../api/client";
import { ApiError } from "../../api/errors";
import { parseReconstruction } from "../../api/parsers";
import type { Operation, Reconstruction } from "../../api/types";
import fixture from "../../test/contract-fixtures/reconstruction-empty-verifications-v1.json";
import { CommandAttemptRegistry } from "../commands/attemptRegistry";
import { CommandController } from "../commands/commandController";
import { ApprovalsPage } from "./ApprovalsPage";

const parsed = parseReconstruction(fixture);
const waiting: Operation = {
  ...parsed.operation,
  state: "AWAITING_APPROVAL",
  version: 3,
  current_approval_id: "approval-current",
  intent: {
    ...parsed.operation.intent,
    arguments: {
      owner: "octo-org", repo: "stateback", title: "Safe issue",
      labels: ["safety"], assignees: ["operator"], body: "private body",
      unknown_argument: "must-not-render",
    },
  },
};
const detail: Reconstruction = {
  ...parsed,
  operation: waiting,
  approvals: [{
    contract_version: "v1", approval_id: "approval-current", operation_id: waiting.operation_id,
    operation_version: 3, intent_digest: waiting.intent.intent_digest, policy_decision_id: "policy-1",
    state: "PENDING", requested_at: "2026-08-20T12:00:00Z", expires_at: null,
    decided_at: null, decided_by: null, reason: null,
  }],
  available_actions: ["approve", "reject"],
};

function makeClient(overrides: Partial<OperatorClient> = {}): OperatorClient {
  return {
    overview: vi.fn(),
    list: vi.fn().mockResolvedValue({ contract_version: "v1", items: [waiting, { ...waiting, operation_id: "second-operation" }], next_cursor: null }),
    reconstruct: vi.fn().mockResolvedValue(detail),
    semanticSummary: vi.fn(),
    command: vi.fn().mockResolvedValue({ ...waiting, state: "READY", version: 4 }),
    ...overrides,
  };
}

async function selectFirstApproval() {
  const links = await screen.findAllByRole("link", { name: /create issue with github/i });
  fireEvent.click(links[0]);
}

test("loads one exact-state queue request and reconstructs only the selected row", async () => {
  const client = makeClient();
  render(<ApprovalsPage client={client} />);
  expect(await screen.findByText("second-operation")).toBeVisible();
  expect(client.list).toHaveBeenCalledWith({ state: "AWAITING_APPROVAL", limit: 50 }, expect.any(AbortSignal));
  expect(client.reconstruct).not.toHaveBeenCalled();
  const queue = screen.getByRole("heading", { name: "Awaiting approval" }).parentElement!;
  fireEvent.click(within(queue).getAllByRole("link", { name: /create issue with github/i })[0]);
  expect(await screen.findByRole("heading", { name: "Create issue" })).toBeVisible();
  expect(client.reconstruct).toHaveBeenCalledTimes(1);
  expect(client.reconstruct).toHaveBeenCalledWith(waiting.operation_id, expect.any(AbortSignal));
  expect(screen.queryByRole("button", { name: /approve all/i })).not.toBeInTheDocument();
});

test("renders exact binding, safe GitHub allowlist, and backend-authorized actions only", async () => {
  const client = makeClient();
  render(<ApprovalsPage client={client} />);
  await selectFirstApproval();
  await screen.findByRole("heading", { name: "Create issue" });
  expect(screen.getByText("octo-org/stateback")).toBeVisible();
  expect(screen.getAllByText("Safe issue").find((node) => node.closest("details") === null)).toBeVisible();
  expect(screen.getByText("Approval authorizes").nextElementSibling).toHaveTextContent("Create issue with GitHub");
  expect(screen.queryByText("private body")).not.toBeInTheDocument();
  expect(screen.queryByText("must-not-render")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Approve create issue" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Reject create issue" })).toBeVisible();
  expect(screen.queryByRole("button", { name: /verification/i })).not.toBeInTheDocument();
});

test("makes merge approval bind the pull request, expected head, and method", async () => {
  const mergeWaiting: Operation = {
    ...waiting,
    risk_level: "HIGH",
    intent: {
      ...waiting.intent,
      effect: { provider: "github", action: "merge_pull_request", version: "v1" },
      arguments: {
        owner: "octo-org",
        repo: "stateback",
        pull_number: 123,
        head_sha: "abcdef1234567890abcdef1234567890abcdef12",
        merge_method: "squash",
      },
    },
  };
  const mergeDetail: Reconstruction = {
    ...detail,
    operation: mergeWaiting,
    approvals: detail.approvals.map((approval) => ({
      ...approval,
      operation_id: mergeWaiting.operation_id,
      intent_digest: mergeWaiting.intent.intent_digest,
    })),
  };
  const client = makeClient({
    list: vi.fn().mockResolvedValue({ contract_version: "v1", items: [mergeWaiting], next_cursor: null }),
    reconstruct: vi.fn().mockResolvedValue(mergeDetail),
  });

  render(<ApprovalsPage client={client} />);
  fireEvent.click(await screen.findByRole("link", { name: /merge pull request with github/i }));

  expect(await screen.findByRole("heading", { name: "Merge pull request" })).toBeVisible();
  expect(screen.getAllByText("#123")[0]).toBeVisible();
  expect(screen.getAllByText("abcdef1234567890abcdef1234567890abcdef12")[0]).toBeVisible();
  expect(screen.getAllByText("squash")[0]).toBeVisible();
  expect(screen.getByRole("button", { name: "Approve merge pull request" })).toBeVisible();
});

test("confirms the normalized exact binding and reloads before changing canonical display", async () => {
  const fresh = { ...detail, operation: { ...waiting, state: "READY", version: 4 }, available_actions: [] };
  const client = makeClient({
    list: vi.fn()
      .mockResolvedValueOnce({ contract_version: "v1", items: [waiting], next_cursor: null })
      .mockResolvedValueOnce({ contract_version: "v1", items: [], next_cursor: null }),
    reconstruct: vi.fn().mockResolvedValueOnce(detail).mockResolvedValueOnce(fresh),
  });
  const ids = ["idem-1", "corr-1"];
  const controller = new CommandController(client, { registry: new CommandAttemptRegistry(), makeId: () => ids.shift()! });
  render(<ApprovalsPage client={client} commandController={controller} />);
  await selectFirstApproval();
  await screen.findByRole("heading", { name: "Create issue" });
  fireEvent.change(screen.getByLabelText("Operator reason"), { target: { value: "  reviewed safely  " } });
  fireEvent.click(screen.getByRole("button", { name: "Approve create issue" }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("approval-current")).toBeVisible();
  expect(within(dialog).getByText("reviewed safely")).toBeVisible();
  fireEvent.click(within(dialog).getByRole("button", { name: "Approve create issue" }));
  await waitFor(() => expect(client.command).toHaveBeenCalledWith({
    operationId: waiting.operation_id, actionKey: "approve", expectedVersion: 3,
    approvalId: "approval-current", reason: "reviewed safely", idempotencyKey: "idem-1", correlationId: "corr-1",
  }));
  await waitFor(() => expect(client.reconstruct).toHaveBeenCalledTimes(2));
  expect(await screen.findByText("Authoritative reconstruction reloaded.")).toBeVisible();
  expect(screen.getByText("No approvals waiting")).toBeVisible();
});

test("stale conflict preserves reason and renders refreshed version without optimistic success", async () => {
  const stale = { ...detail, operation: { ...waiting, version: 4 }, available_actions: ["approve", "reject"] };
  const client = makeClient({
    reconstruct: vi.fn().mockResolvedValueOnce(detail).mockResolvedValueOnce(stale),
    command: vi.fn().mockRejectedValue(new ApiError({ status: 409, code: "stale", safeMessage: "Version changed", retryable: false, correlationId: "safe-correlation" })),
  });
  const controller = new CommandController(client, { registry: new CommandAttemptRegistry(), makeId: vi.fn().mockReturnValueOnce("idem").mockReturnValueOnce("corr") });
  render(<ApprovalsPage client={client} commandController={controller} />);
  await selectFirstApproval();
  await screen.findByRole("heading", { name: "Create issue" });
  fireEvent.change(screen.getByLabelText("Operator reason"), { target: { value: "keep this reason" } });
  fireEvent.click(screen.getByRole("button", { name: "Approve create issue" }));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve create issue" }));
  expect(await screen.findByText("Approval changed on the server")).toBeVisible();
  expect(screen.getByLabelText("Operator reason")).toHaveValue("keep this reason");
  expect(screen.getByText("Your reason is preserved. Review the authoritative version before confirming a new request.")).toBeVisible();
  expect(screen.queryByText(/external effect complete/i)).not.toBeInTheDocument();
});

test("omits approval controls when backend returns no eligible action", async () => {
  const client = makeClient({ reconstruct: vi.fn().mockResolvedValue({ ...detail, available_actions: [] }) });
  render(<ApprovalsPage client={client} />);
  await selectFirstApproval();
  await screen.findByRole("heading", { name: "Create issue" });
  expect(screen.queryByRole("button", { name: "Approve create issue" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Reject create issue" })).not.toBeInTheDocument();
});
