import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { CommandOutcome } from "./CommandOutcome";
import { CopyableId } from "./CopyableId";
import { DefensiveState } from "./DefensiveState";
import { Timestamp } from "./Timestamp";

test("renders UTC timestamps and rejects invalid input safely", () => {
  const { rerender } = render(<Timestamp value="2026-08-20T12:30:00Z" />);
  expect(screen.getByText(/2026-08-20T12:30:00.000Z UTC/)).toHaveAttribute("datetime", "2026-08-20T12:30:00Z");
  rerender(<Timestamp value="not-a-time" />);
  expect(screen.getByRole("status")).toHaveTextContent("Invalid timestamp");
});

test("copies only the displayed full identifier and announces success", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  render(<CopyableId value="operation-123" label="operation ID" />);
  fireEvent.click(screen.getByRole("button", { name: "Copy operation ID operation-123" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("operation-123"));
  expect(screen.getByRole("status")).toHaveTextContent("operation ID copied");
});

test("defensive and command request states use live semantics without state badges", () => {
  const retry = vi.fn();
  const { rerender } = render(
    <DefensiveState kind="error" title="Unable to load" onRetry={retry}>Canonical state is unchanged.</DefensiveState>,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Canonical state is unchanged.");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(retry).toHaveBeenCalledOnce();

  rerender(<CommandOutcome kind="accepted-reloading" title="Command accepted">Reloading authoritative state.</CommandOutcome>);
  expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
  expect(screen.queryByText(/SUCCEEDED|FAILED/)).not.toBeInTheDocument();
});

test("authoritative reload is neutral while rate limiting is a distinct alert", () => {
  const { rerender } = render(
    <CommandOutcome kind="authoritative-reloaded" title="Authoritative state reloaded">Eligibility changed without an inferred outcome.</CommandOutcome>,
  );
  expect(screen.getByRole("status")).toHaveClass("command-outcome--authoritative-reloaded");
  expect(screen.getByRole("status")).not.toHaveAttribute("aria-busy");
  expect(screen.queryByText(/accepted|succeeded/i)).not.toBeInTheDocument();

  rerender(<CommandOutcome kind="rate-limited" title="Rate limited">No automatic retry was attempted.</CommandOutcome>);
  expect(screen.getByRole("alert")).toHaveClass("command-outcome--rate-limited");
  expect(screen.getByRole("alert")).toHaveTextContent("No automatic retry was attempted.");
});
