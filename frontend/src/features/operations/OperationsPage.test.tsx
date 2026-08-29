import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import type { OperatorClient } from "../../api/client";
import type { Operation, OperationPage } from "../../api/types";
import { OperationsPage } from "./OperationsPage";

function operation(id: string, state = "UNKNOWN"): Operation {
  return {
    contract_version: "v1", operation_id: id, state, version: 1,
    intent: {
      effect: { provider: "github", action: "create_issue", version: "v1" },
      arguments_mode: "INLINE", arguments: {}, arguments_ref: null,
      canonical_arguments_hash: "hash", intent_digest: "digest",
      requester: { type: "SERVICE", id: "agent", display_name: null },
      requested_at: "2026-08-20T10:00:00Z", metadata: {},
    },
    risk_level: "LOW", idempotency_identity: "identity", current_policy_decision_id: null,
    current_approval_id: null, latest_attempt_id: null, latest_verification_id: null,
    compensation_id: null, created_at: "2026-08-20T10:00:00Z", updated_at: "2026-08-20T10:00:00Z",
  };
}

function clientWithList(list: OperatorClient["list"]): OperatorClient {
  return {
    overview: vi.fn(),
    list,
    reconstruct: vi.fn(),
    semanticSummary: vi.fn(),
    command: vi.fn(),
  };
}

function page(items: Operation[], next_cursor: string | null = null): OperationPage {
  return { contract_version: "v1", items, next_cursor };
}

test("loads exact URL filters and preserves backend order", async () => {
  const list = vi.fn().mockResolvedValue(page([operation("op-b"), operation("op-a", "SUCCEEDED")], "next"));
  render(<OperationsPage client={clientWithList(list)} search="?state=UNKNOWN&provider=github&created_from=2026-08-20T00%3A00%3A00Z&created_to=2026-08-20T23%3A59%3A00Z&limit=25" navigate={vi.fn()} />);
  expect(await screen.findByText("op-b")).toBeVisible();
  const rows = screen.getAllByRole("row").slice(1);
  expect(rows[0]).toHaveTextContent("op-b");
  expect(rows[1]).toHaveTextContent("op-a");
  expect(list).toHaveBeenCalledWith({
    state: "UNKNOWN", provider: "github", createdFrom: "2026-08-20T00:00:00Z",
    createdTo: "2026-08-20T23:59:00Z", limit: 25,
  }, expect.any(AbortSignal));
  expect(screen.queryByText(/of \d+/i)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/search/i)).not.toBeInTheDocument();
});

test("uses opaque next cursor and client-only previous history", async () => {
  const list = vi.fn()
    .mockResolvedValueOnce(page([operation("first")], "opaque+next/="))
    .mockResolvedValueOnce(page([operation("second")], null))
    .mockResolvedValueOnce(page([operation("first")], "opaque+next/="));
  render(<OperationsPage client={clientWithList(list)} search="?limit=10" navigate={vi.fn()} />);
  await screen.findByText("first");
  expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByText("second");
  expect(list.mock.calls[1][0]).toEqual({ limit: 10, cursor: "opaque+next/=" });
  fireEvent.click(screen.getByRole("button", { name: "Previous" }));
  await waitFor(() => expect(screen.getByText("first")).toBeVisible());
  expect(list.mock.calls[2][0]).toEqual({ limit: 10 });
});

test("filter navigation is deterministic and separate from exact-ID navigation", async () => {
  const navigate = vi.fn();
  render(<OperationsPage client={clientWithList(vi.fn().mockResolvedValue(page([])))} search="" navigate={navigate} />);
  await screen.findByText("No operations yet");
  fireEvent.change(screen.getByLabelText("State"), { target: { value: "NEEDS_ATTENTION" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  expect(navigate).toHaveBeenCalledWith("/operations?attention=true&limit=50");
  fireEvent.change(screen.getByLabelText("State"), { target: { value: "UNKNOWN" } });
  fireEvent.change(screen.getByLabelText("Provider (exact)"), { target: { value: " github " } });
  fireEvent.change(screen.getByLabelText("Results per page"), { target: { value: "20" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  expect(navigate).toHaveBeenCalledWith("/operations?state=UNKNOWN&provider=github&limit=20");
  fireEvent.change(screen.getByLabelText("Exact operation ID"), { target: { value: "opaque:id" } });
  fireEvent.click(screen.getByRole("button", { name: "Open operation" }));
  expect(navigate).toHaveBeenLastCalledWith("/operations/opaque%3Aid");
});

test("filter change aborts the old read and ignores its late result", async () => {
  let resolveOld!: (value: OperationPage) => void;
  const old = new Promise<OperationPage>((resolve) => { resolveOld = resolve; });
  const list = vi.fn()
    .mockReturnValueOnce(old)
    .mockResolvedValueOnce(page([operation("fresh")]));
  const { rerender } = render(<OperationsPage client={clientWithList(list)} search="?state=UNKNOWN" navigate={vi.fn()} />);
  const firstSignal = list.mock.calls[0][1] as AbortSignal;
  rerender(<OperationsPage client={clientWithList(list)} search="?state=FAILED" navigate={vi.fn()} />);
  expect(firstSignal.aborted).toBe(true);
  expect(await screen.findByText("fresh")).toBeVisible();
  resolveOld(page([operation("stale")]));
  await Promise.resolve();
  expect(screen.queryByText("stale")).not.toBeInTheDocument();
});

test("renders loading, empty, retryable error, and unsupported URL safely", async () => {
  const list = vi.fn().mockRejectedValueOnce(new Error("Backend unavailable")).mockResolvedValueOnce(page([]));
  render(<OperationsPage client={clientWithList(list)} search="?state=NOT_REAL&total=100" navigate={vi.fn()} />);
  expect(screen.getByText("Loading operations")).toBeVisible();
  expect(await screen.findByRole("alert")).toHaveTextContent("Unsupported operation filters were ignored.");
  expect(await screen.findByText("Backend unavailable")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("No operations match these filters")).toBeVisible();
  expect(list).toHaveBeenLastCalledWith({ limit: 50 }, expect.any(AbortSignal));
});
