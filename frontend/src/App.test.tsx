import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import { App, StateBadge } from "./App";
import { createOperatorApi, type OperatorApi } from "./api";
import type { Operation, Reconstruction } from "./types";

const operation: Operation = {
  contract_version: "v1",
  operation_id: "00000000-0000-4000-8000-000000000001",
  state: "UNKNOWN",
  version: 4,
  created_at: "2026-08-17T12:00:00Z",
  updated_at: "2026-08-17T12:01:00Z",
  intent: { effect: { provider: "github", action: "create_issue", version: "v1" } },
  current_approval_id: null,
  compensation_id: null,
};

const reconstruction: Reconstruction = {
  contract_version: "v1",
  operation,
  available_actions: [],
  audit: [{
    audit_event_id: "00000000-0000-4000-8000-000000000008",
    sequence: 1,
    event_type: "execution.evidence_recorded.v1",
    reason_code: "provider_outcome_unknown",
    from_state: "EXECUTING",
    to_state: "UNKNOWN",
    correlation_id: "corr-1",
    created_at: "2026-08-17T12:01:00Z",
  }],
};

test("unknown is visibly distinct from failure", () => {
  render(<StateBadge state="UNKNOWN" />);
  expect(screen.getByText("UNKNOWN")).toHaveClass("uncertain");
  expect(screen.queryByText("FAILED")).not.toBeInTheDocument();
});

test("future state is rendered safely", () => {
  render(<StateBadge state="FUTURE_STATE" />);
  expect(screen.getByText("Unsupported state: FUTURE_STATE")).toBeVisible();
});

test("timeline uses backend audit and exposes no raw arguments", async () => {
  const api: OperatorApi = {
    list: vi.fn().mockResolvedValue([operation]),
    reconstruct: vi.fn().mockResolvedValue(reconstruction),
    control: vi.fn(),
  };
  render(<App api={api} />);
  await screen.findByText("github / create_issue");
  fireEvent.click(screen.getByText("github / create_issue"));
  await screen.findByText("execution.evidence_recorded.v1");
  expect(screen.getByText("provider_outcome_unknown")).toBeVisible();
  expect(screen.queryByText("arguments")).not.toBeInTheDocument();
});

test("dangerous action waits for confirmation and server", async () => {
  const compensatable = { ...operation, state: "SUCCEEDED" };
  const detail = { ...reconstruction, operation: compensatable, available_actions: ["compensate"] };
  const api: OperatorApi = {
    list: vi.fn().mockResolvedValue([compensatable]),
    reconstruct: vi.fn().mockResolvedValue(detail),
    control: vi.fn().mockResolvedValue({ ...compensatable, state: "COMPENSATING" }),
  };
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.spyOn(window, "prompt").mockReturnValue("operator-requested");
  render(<App api={api} />);
  await screen.findByText("github / create_issue");
  fireEvent.click(screen.getByText("github / create_issue"));
  fireEvent.click(await screen.findByText("Start compensation"));
  await waitFor(() => expect(api.control).toHaveBeenCalledOnce());
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining(operation.operation_id));
});

test("approval controls are shown only for awaiting approval", async () => {
  const awaiting = {
    ...operation,
    state: "AWAITING_APPROVAL",
    current_approval_id: "00000000-0000-4000-8000-000000000004",
  };
  const api: OperatorApi = {
    list: vi.fn().mockResolvedValue([awaiting]),
    reconstruct: vi.fn().mockResolvedValue({ ...reconstruction, operation: awaiting, available_actions: ["approve", "reject"] }),
    control: vi.fn(),
  };
  render(<App api={api} />);
  await screen.findByText("github / create_issue");
  fireEvent.click(screen.getByText("github / create_issue"));
  expect(await screen.findByText("Approve operation")).toBeVisible();
  expect(screen.getByText("Reject operation")).toBeVisible();
  expect(screen.queryByText("Retry compensation")).not.toBeInTheDocument();
});

test("state alone never exposes a capability-dependent action", async () => {
  const succeeded = { ...operation, state: "SUCCEEDED" };
  const api: OperatorApi = {
    list: vi.fn().mockResolvedValue([succeeded]),
    reconstruct: vi.fn().mockResolvedValue({ ...reconstruction, operation: succeeded, available_actions: [] }),
    control: vi.fn(),
  };
  render(<App api={api} />);
  fireEvent.click(await screen.findByText("github / create_issue"));
  await screen.findByText("SUCCEEDED");
  expect(screen.queryByText("Start compensation")).not.toBeInTheDocument();
});

test("backend errors are announced without inventing state", async () => {
  const api: OperatorApi = {
    list: vi.fn().mockRejectedValue(new Error("Service unavailable")),
    reconstruct: vi.fn(),
    control: vi.fn(),
  };
  render(<App api={api} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Service unavailable");
  expect(screen.queryByText("FAILED")).not.toBeInTheDocument();
});

test("critical navigation and controls have accessible names", async () => {
  const api: OperatorApi = {
    list: vi.fn().mockResolvedValue([operation]),
    reconstruct: vi.fn().mockResolvedValue(reconstruction),
    control: vi.fn(),
  };
  render(<App api={api} />);
  expect(await screen.findByRole("button", { name: /github \/ create_issue/i })).toBeVisible();
  expect(screen.getByRole("button", { name: "Refresh" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "Operation detail" })).toBeVisible();
});

test("operator API controls carry a correlation identifier", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => operation,
  });
  vi.stubGlobal("fetch", fetchMock);
  const api = createOperatorApi("https://stateback.test", () => "operator-token");
  await api.control(
    { ...operation, state: "SUCCEEDED" },
    "compensate",
    "operator requested",
  );
  const init = fetchMock.mock.calls[0][1] as RequestInit;
  const headers = init.headers as Record<string, string>;
  expect(headers["X-Correlation-ID"]).toMatch(/^[0-9a-f-]{36}$/);
  vi.unstubAllGlobals();
});
