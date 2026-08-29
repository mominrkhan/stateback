import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { OperatorClient } from "../../api/client";
import { parseOperationPage } from "../../api/parsers";
import type { OperatorOverview } from "../../api/types";
import listFixture from "../../test/contract-fixtures/operation-list-v1.json";
import { OverviewPage } from "./OverviewPage";

const operation = parseOperationPage(listFixture).items[0];

function overview(overrides: Partial<OperatorOverview> = {}): OperatorOverview {
  return {
    contract_version: "v1",
    total_operations: 0,
    attention: { awaiting_approval: 0, unknown: 0, manual_intervention: 0, compensation_issues: 0 },
    active: { executing: 0, verifying: 0, compensating: 0 },
    recent_operations: [],
    providers: [{ provider: "github", configured: false, supported_effects: [{ provider: "github", action: "create_issue", version: "v1" }] }],
    ...overrides,
  };
}

function client(result: Promise<OperatorOverview>): OperatorClient {
  return { overview: vi.fn(() => result), list: vi.fn(), reconstruct: vi.fn(), semanticSummary: vi.fn(), command: vi.fn() };
}

test("renders loading then derived onboarding for zero operations and unconfigured GitHub", async () => {
  let resolve!: (value: OperatorOverview) => void;
  render(<OverviewPage client={client(new Promise((done) => { resolve = done; }))} navigate={vi.fn()} />);
  expect(screen.getByText("Loading overview")).toBeVisible();
  resolve(overview());
  expect(await screen.findByRole("heading", { name: "Welcome to Stateback" })).toBeVisible();
  expect(screen.getAllByText("stateback connect github").length).toBeGreaterThan(0);
  expect(screen.getByRole("heading", { name: "Why UNKNOWN exists" })).toBeVisible();
  expect(screen.queryByText(/onboarding_complete/i)).not.toBeInTheDocument();
});

test("shows configured onboarding without a setup command", async () => {
  const configured = overview({ providers: [{ provider: "github", configured: true, supported_effects: [{ provider: "github", action: "create_issue", version: "v1" }] }] });
  render(<OverviewPage client={client(Promise.resolve(configured))} navigate={vi.fn()} />);
  expect(await screen.findByText("GitHub configured")).toBeVisible();
  expect(screen.queryByText("stateback connect github")).not.toBeInTheDocument();
});

test("renders exact attention, active, and recent operation data and navigates filters", async () => {
  const navigate = vi.fn();
  render(<OverviewPage client={client(Promise.resolve(overview({
    total_operations: 7,
    attention: { awaiting_approval: 1, unknown: 2, manual_intervention: 1, compensation_issues: 2 },
    active: { executing: 1, verifying: 2, compensating: 3 },
    recent_operations: [{ ...operation, state: "UNKNOWN" }],
  })))} navigate={navigate} />);
  await screen.findByRole("heading", { name: "Recent activity" });
  expect(screen.queryByText("No operations yet")).not.toBeInTheDocument();
  const unknownLink = screen.getAllByText("Outcome unknown")[0].closest("a");
  expect(unknownLink).not.toBeNull();
  expect(unknownLink).toHaveTextContent("2");
  const approvalLink = screen.getByText("Awaiting approval").closest("a");
  const manualLink = screen.getByText("Manual intervention").closest("a");
  const compensationLink = screen.getByText("Compensation issue").closest("a");
  expect(approvalLink).toHaveTextContent("1");
  expect(manualLink).toHaveTextContent("1");
  expect(compensationLink).toHaveTextContent("2");
  expect(screen.getByText("Verifying").nextElementSibling).toHaveTextContent("2");
  expect(screen.getByText("Create issue")).toBeVisible();
  fireEvent.click(approvalLink!);
  fireEvent.click(unknownLink!);
  fireEvent.click(manualLink!);
  fireEvent.click(compensationLink!);
  expect(navigate.mock.calls).toEqual([
    ["/approvals"],
    ["/operations?state=UNKNOWN&limit=50"],
    ["/operations?state=MANUAL_INTERVENTION&limit=50"],
    ["/recovery"],
  ]);
});

test("shows the clear state when no operation needs attention", async () => {
  render(<OverviewPage client={client(Promise.resolve(overview({ total_operations: 1, recent_operations: [operation] })))} navigate={vi.fn()} />);
  expect(await screen.findByText(/No operations need attention/)).toBeVisible();
});

test("renders an actionable API failure and retries", async () => {
  const overviewRead = vi.fn().mockRejectedValueOnce(new Error("Network request failed")).mockResolvedValueOnce(overview());
  const fake: OperatorClient = { overview: overviewRead, list: vi.fn(), reconstruct: vi.fn(), semanticSummary: vi.fn(), command: vi.fn() };
  render(<OverviewPage client={fake} navigate={vi.fn()} />);
  expect(await screen.findByRole("heading", { name: "Could not load overview" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(overviewRead).toHaveBeenCalledTimes(2));
  expect(await screen.findByRole("heading", { name: "Welcome to Stateback" })).toBeVisible();
});

test("copies the GitHub setup command", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  render(<OverviewPage client={client(Promise.resolve(overview()))} navigate={vi.fn()} />);
  fireEvent.click((await screen.findAllByRole("button", { name: "Copy command" }))[0]);
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("stateback connect github"));
});
