import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import { App, StateBadge } from "./App";
import { createOperatorApi, parseSemanticSummary, type OperatorApi } from "./api";
import type { Operation, Reconstruction, SemanticSummary } from "./types";

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

const semanticSummary: SemanticSummary = {
  contract_version: "v1",
  advisory: true,
  status: "AVAILABLE",
  summary: "The provider outcome remains unknown.",
  key_events: [{ sequence: 1, description: "Unknown execution evidence" }],
  unresolved_uncertainties: ["Whether the external effect occurred"],
  confidence: 0.82,
  summarized_operation_version: 4,
  summarized_through_sequence: 1,
  provenance: {
    provider: "ollama",
    model: "qwen3",
    prompt_version: "audit-summary-v1",
    output_schema_version: "v1",
  },
  reason_code: "semantic_summary_available",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

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
    summarize: vi.fn(),
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
    summarize: vi.fn(),
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
    summarize: vi.fn(),
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
    summarize: vi.fn(),
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
    summarize: vi.fn(),
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
    summarize: vi.fn(),
    control: vi.fn(),
  };
  render(<App api={api} />);
  expect(await screen.findByRole("button", { name: /github \/ create_issue/i })).toBeVisible();
  expect(screen.getByRole("button", { name: "Refresh" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "Operation detail" })).toBeVisible();
});

test("semantic summary is requested explicitly and labeled non-authoritative", async () => {
  const api: OperatorApi = {
    list: vi.fn().mockResolvedValue([operation]),
    reconstruct: vi.fn().mockResolvedValue(reconstruction),
    summarize: vi.fn().mockResolvedValue(semanticSummary),
    control: vi.fn(),
  };
  render(<App api={api} />);
  fireEvent.click(await screen.findByText("github / create_issue"));
  expect(await screen.findByText(/Model-generated and non-authoritative/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Generate summary" }));
  expect(await screen.findByText("The provider outcome remains unknown.")).toBeVisible();
  expect(screen.getByText("Whether the external effect occurred")).toBeVisible();
  expect(screen.getByText("execution.evidence_recorded.v1")).toBeVisible();
  expect(api.control).not.toHaveBeenCalled();
});

test("semantic unavailability does not invent operation failure", async () => {
  const api: OperatorApi = {
    list: vi.fn().mockResolvedValue([operation]),
    reconstruct: vi.fn().mockResolvedValue(reconstruction),
    summarize: vi.fn().mockResolvedValue({
      ...semanticSummary,
      status: "UNAVAILABLE",
      summary: null,
      key_events: [],
      unresolved_uncertainties: [],
      confidence: null,
      reason_code: "semantic_not_configured",
    }),
    control: vi.fn(),
  };
  render(<App api={api} />);
  fireEvent.click(await screen.findByText("github / create_issue"));
  fireEvent.click(await screen.findByRole("button", { name: "Generate summary" }));
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Semantic assistance unavailable: semantic_not_configured",
  );
  expect(screen.getAllByText("UNKNOWN")).toHaveLength(2);
  expect(screen.queryByText("FAILED")).not.toBeInTheDocument();
});

test("late semantic response is ignored after selecting another operation", async () => {
  const pending = deferred<SemanticSummary>();
  const second = {
    ...operation,
    operation_id: "00000000-0000-4000-8000-000000000002",
    intent: { effect: { provider: "github", action: "close_issue", version: "v1" } },
  };
  const api: OperatorApi = {
    list: vi.fn().mockResolvedValue([operation, second]),
    reconstruct: vi.fn().mockImplementation(async (operationId: string) => ({
      ...reconstruction,
      operation: operationId === second.operation_id ? second : operation,
    })),
    summarize: vi.fn().mockReturnValue(pending.promise),
    control: vi.fn(),
  };
  render(<App api={api} />);
  fireEvent.click(await screen.findByText("github / create_issue"));
  fireEvent.click(await screen.findByRole("button", { name: "Generate summary" }));
  fireEvent.click(screen.getByText("github / close_issue"));
  await waitFor(() => expect(api.reconstruct).toHaveBeenLastCalledWith(second.operation_id));
  await act(async () => pending.resolve(semanticSummary));
  expect(screen.queryByText("The provider outcome remains unknown.")).not.toBeInTheDocument();
});

test("successful control clears a prior semantic summary", async () => {
  const succeeded = { ...operation, state: "SUCCEEDED", version: 4 };
  const compensating = { ...succeeded, state: "COMPENSATING", version: 5 };
  const before = { ...reconstruction, operation: succeeded, available_actions: ["compensate"] };
  const after = { ...reconstruction, operation: compensating, available_actions: [] };
  const api: OperatorApi = {
    list: vi.fn().mockResolvedValue([succeeded]),
    reconstruct: vi.fn().mockResolvedValueOnce(before).mockResolvedValueOnce(after),
    summarize: vi.fn().mockResolvedValue(semanticSummary),
    control: vi.fn().mockResolvedValue(compensating),
  };
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.spyOn(window, "prompt").mockReturnValue("operator-requested");
  render(<App api={api} />);
  fireEvent.click(await screen.findByText("github / create_issue"));
  fireEvent.click(await screen.findByRole("button", { name: "Generate summary" }));
  expect(await screen.findByText("The provider outcome remains unknown.")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Start compensation" }));
  await waitFor(() => expect(api.control).toHaveBeenCalledOnce());
  expect(screen.queryByText("The provider outcome remains unknown.")).not.toBeInTheDocument();
  expect(await screen.findByText("COMPENSATING")).toBeVisible();
});

test("summary for a different operation version is rejected as stale", async () => {
  const api: OperatorApi = {
    list: vi.fn().mockResolvedValue([operation]),
    reconstruct: vi.fn().mockResolvedValue(reconstruction),
    summarize: vi.fn().mockResolvedValue({
      ...semanticSummary,
      summarized_operation_version: operation.version + 1,
    }),
    control: vi.fn(),
  };
  render(<App api={api} />);
  fireEvent.click(await screen.findByText("github / create_issue"));
  fireEvent.click(await screen.findByRole("button", { name: "Generate summary" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Operation changed while semantic assistance was running",
  );
  expect(screen.queryByText("The provider outcome remains unknown.")).not.toBeInTheDocument();
});

test.each([
  { status: "SUCCEEDED" },
  { provenance: { ...semanticSummary.provenance, prompt_version: "future" } },
  { summarized_operation_version: 1.5 },
  { summarized_through_sequence: -1 },
  { confidence: null },
  { confidence: 0.49 },
  { key_events: [{ sequence: 2, description: "not in summarized range" }] },
  { status: "UNAVAILABLE", reason_code: "semantic_model_unavailable" },
])("semantic parser rejects incompatible v1 response %#", (change) => {
  expect(() => parseSemanticSummary({ ...semanticSummary, ...change })).toThrow(
    "Unsupported or malformed semantic summary response",
  );
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

test("operator API requests semantic summary without control headers", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => semanticSummary,
  });
  vi.stubGlobal("fetch", fetchMock);
  const api = createOperatorApi("https://stateback.test", () => "operator-token");
  const result = await api.summarize(operation.operation_id);
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toContain("/semantic-summary");
  expect(init.method).toBe("POST");
  expect((init.headers as Record<string, string>)["Idempotency-Key"]).toBeUndefined();
  expect(init.body).toBe(JSON.stringify({ contract_version: "v1" }));
  expect(result.advisory).toBe(true);
  vi.unstubAllGlobals();
});
