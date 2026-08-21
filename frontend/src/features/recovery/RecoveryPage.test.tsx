import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { OperatorClient } from "../../api/client";
import { parseReconstruction } from "../../api/parsers";
import type { OperationFilters } from "../../api/query";
import type { Operation, Reconstruction } from "../../api/types";
import fixture from "../../test/contract-fixtures/reconstruction-empty-verifications-v1.json";
import { CommandAttemptRegistry } from "../commands/attemptRegistry";
import { RecoveryPage } from "./RecoveryPage";

const base = parseReconstruction(fixture);

function operation(state: string, id = `operation-${state.toLowerCase()}`): Operation {
  return { ...base.operation, operation_id: id, state };
}

function reconstruction(item: Operation, actions: string[]): Reconstruction {
  return { ...base, operation: item, available_actions: actions };
}

function makeClient(options: {
  operations?: Record<string, Operation[]>;
  selected?: Reconstruction;
  afterCommand?: Reconstruction;
} = {}): OperatorClient {
  const operations = options.operations ?? {};
  const selected = options.selected ?? reconstruction(operation("MANUAL_INTERVENTION"), ["verify"]);
  const afterCommand = options.afterCommand ?? { ...selected, operation: { ...selected.operation, version: selected.operation.version + 1 }, available_actions: [] };
  let reconstructionCalls = 0;
  return {
    list: vi.fn(async (filters?: OperationFilters) => ({ contract_version: "v1" as const, items: operations[filters?.state ?? ""] ?? [], next_cursor: null })),
    reconstruct: vi.fn(async () => ++reconstructionCalls === 1 ? selected : afterCommand),
    command: vi.fn(async () => afterCommand.operation),
    semanticSummary: vi.fn(),
  };
}

test("loads four separate exact-state queues without reconstruction N+1 and excludes UNKNOWN", async () => {
  const manual = operation("MANUAL_INTERVENTION");
  const unknown = operation("UNKNOWN");
  const client = makeClient({
    operations: {
      MANUAL_INTERVENTION: [manual],
      COMPENSATION_UNKNOWN: [],
      COMPENSATION_FAILED: [],
      COMPENSATING: [],
      UNKNOWN: [unknown],
    },
  });
  render(<RecoveryPage client={client} attemptRegistry={new CommandAttemptRegistry()} />);
  await screen.findByText("operation-manual_intervention", { exact: false });
  expect(client.list).toHaveBeenCalledTimes(4);
  expect(client.list).toHaveBeenNthCalledWith(1, { state: "MANUAL_INTERVENTION", limit: 50 }, expect.any(AbortSignal));
  expect(client.list).toHaveBeenNthCalledWith(2, { state: "COMPENSATION_UNKNOWN", limit: 50 }, expect.any(AbortSignal));
  expect(client.list).toHaveBeenNthCalledWith(3, { state: "COMPENSATION_FAILED", limit: 50 }, expect.any(AbortSignal));
  expect(client.list).toHaveBeenNthCalledWith(4, { state: "COMPENSATING", limit: 50 }, expect.any(AbortSignal));
  expect(client.reconstruct).not.toHaveBeenCalled();
  expect(screen.queryByText("operation-unknown", { exact: false })).not.toBeInTheDocument();
  expect(screen.getByText(/An operation in UNKNOWN is not included as actionable here/)).toBeVisible();
});

test("loads only the selected reconstruction before rendering exact ActionGate controls", async () => {
  const manual = operation("MANUAL_INTERVENTION");
  const client = makeClient({
    operations: { MANUAL_INTERVENTION: [manual] },
    selected: reconstruction(manual, ["verify", "future_recovery_action"]),
  });
  render(<RecoveryPage client={client} attemptRegistry={new CommandAttemptRegistry()} />);
  fireEvent.click(await screen.findByRole("button", { name: /operation-manual_intervention/i }));
  expect(await screen.findByRole("button", { name: "Request verification" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: /escalate/i })).not.toBeInTheDocument();
  expect(screen.getByText(/Unsupported action unavailable/)).toHaveTextContent("future_recovery_action");
  expect(client.reconstruct).toHaveBeenCalledTimes(1);
});

test.each([
  ["compensate", "Start compensation", "Compensation is another side effect"],
  ["retry_compensation", "Retry compensation", "Compensation is another side effect"],
  ["escalate_compensation", "Escalate compensation", "does not prove rollback"],
] as const)("binds %s to an explicit ambiguity confirmation", async (action, label, warning) => {
  const item = operation(action === "compensate" ? "MANUAL_INTERVENTION" : "COMPENSATION_FAILED");
  const client = makeClient({ operations: { [item.state]: [item] }, selected: reconstruction(item, [action]) });
  render(<RecoveryPage client={client} attemptRegistry={new CommandAttemptRegistry()} />);
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(item.operation_id, "i") }));
  fireEvent.click(await screen.findByRole("button", { name: label }));
  const dialog = screen.getByRole("dialog", { name: label });
  expect(within(dialog).getAllByText(new RegExp(warning)).length).toBeGreaterThan(0);
  expect(within(dialog).getByText(item.operation_id)).toBeVisible();
  expect(within(dialog).getByText(action)).toBeVisible();
  expect(within(dialog).getByText(String(item.version))).toBeVisible();
});

test("submits verification through the command controller and reloads authoritative reconstruction", async () => {
  const item = operation("MANUAL_INTERVENTION");
  const selected = reconstruction(item, ["verify"]);
  const after = { ...selected, operation: { ...item, version: item.version + 1, state: "VERIFYING" }, available_actions: [] };
  const registry = new CommandAttemptRegistry();
  const client = makeClient({ operations: { MANUAL_INTERVENTION: [item] }, selected, afterCommand: after });
  render(<RecoveryPage client={client} attemptRegistry={registry} />);
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(item.operation_id, "i") }));
  fireEvent.click(await screen.findByRole("button", { name: "Request verification" }));
  fireEvent.change(screen.getByLabelText("Operator reason"), { target: { value: "  operator reviewed  " } });
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Request verification" }));
  await waitFor(() => expect(client.command).toHaveBeenCalledOnce());
  expect(client.command).toHaveBeenCalledWith(expect.objectContaining({
    operationId: item.operation_id,
    actionKey: "verify",
    expectedVersion: item.version,
    reason: "operator reviewed",
  }));
  await screen.findByText("Authoritative reconstruction reloaded.");
  expect(client.reconstruct).toHaveBeenCalledTimes(2);
  expect(screen.getByText("VERIFYING")).toBeVisible();
  expect(registry.get(item.operation_id)).toBeUndefined();
});

test("aborts and suppresses late queue results from an obsolete auth session", async () => {
  let resolve!: (page: Awaited<ReturnType<OperatorClient["list"]>>) => void;
  const pending = new Promise<Awaited<ReturnType<OperatorClient["list"]>>>((done) => { resolve = done; });
  const client = makeClient();
  client.list = vi.fn(() => pending);
  const controllers: AbortController[] = [];
  const { rerender } = render(
    <RecoveryPage
      client={client}
      sessionGeneration={1}
      isCurrentGeneration={(generation) => generation === 1}
      createAbortController={() => { const controller = new AbortController(); controllers.push(controller); return controller; }}
    />,
  );
  rerender(
    <RecoveryPage
      client={client}
      sessionGeneration={2}
      isCurrentGeneration={(generation) => generation === 2}
      createAbortController={() => { const controller = new AbortController(); controllers.push(controller); return controller; }}
    />,
  );
  expect(controllers[0].signal.aborted).toBe(true);
  resolve({ contract_version: "v1", items: [operation("UNKNOWN")], next_cursor: null });
  await Promise.resolve();
  expect(screen.queryByText("operation-unknown", { exact: false })).not.toBeInTheDocument();
});
