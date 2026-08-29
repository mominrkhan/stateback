import { render, screen } from "@testing-library/react";

import type { OperatorClient } from "../../api/client";
import type { OperatorOverview } from "../../api/types";
import { ProvidersPage } from "./ProvidersPage";

function client(configured: boolean, failure?: Error): OperatorClient {
  const value: OperatorOverview = {
    contract_version: "v1", total_operations: 0,
    attention: { awaiting_approval: 0, unknown: 0, manual_intervention: 0, compensation_issues: 0 },
    active: { executing: 0, verifying: 0, compensating: 0 }, recent_operations: [],
    providers: [{ provider: "github", configured, supported_effects: [{ provider: "github", action: "create_issue", version: "v1" }] }],
  };
  return { overview: vi.fn(() => failure ? Promise.reject(failure) : Promise.resolve(value)), list: vi.fn(), reconstruct: vi.fn(), semanticSummary: vi.fn(), command: vi.fn() };
}

test("shows configured GitHub and its only supported effect without credential material", async () => {
  render(<ProvidersPage client={client(true)} />);
  expect(await screen.findByText("Configured")).toBeVisible();
  expect(screen.getByText("Create issue")).toBeVisible();
  expect(screen.getByText("github.create_issue.v1")).toBeVisible();
  expect(screen.getByText(/loaded only by provider-executing workers/i)).toBeVisible();
  expect(document.body.textContent).not.toMatch(/github_pat_|ghp_|Reveal token/i);
});

test("shows exact setup and restart guidance when GitHub is not configured", async () => {
  render(<ProvidersPage client={client(false)} />);
  expect(await screen.findByText("Not configured")).toBeVisible();
  expect(screen.getByText("stateback connect github")).toBeVisible();
  expect(screen.getByText(/Restart/)).toHaveTextContent("stateback dev");
});

test("renders provider loading and failure states", async () => {
  render(<ProvidersPage client={client(false, new Error("Network request failed"))} />);
  expect(screen.getByText("Loading providers")).toBeVisible();
  expect(await screen.findByRole("heading", { name: "Could not load providers" })).toBeVisible();
  expect(screen.getByText("Network request failed")).toBeVisible();
});
