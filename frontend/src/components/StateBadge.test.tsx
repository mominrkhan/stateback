import { render, screen } from "@testing-library/react";

import { StateBadge, stateGroup } from "./StateBadge";
import { operationStateLabel } from "../presentation/labels";

const EXPECTED_GROUPS = {
  PENDING_POLICY: "info",
  AWAITING_APPROVAL: "info",
  READY: "info",
  EXECUTING: "active",
  VERIFYING: "unresolved",
  UNKNOWN: "unresolved",
  SUCCEEDED: "success",
  FAILED: "failure",
  DENIED: "failure",
  CANCELLED: "neutral",
  COMPENSATING: "active",
  COMPENSATION_UNKNOWN: "unresolved",
  COMPENSATED: "success",
  COMPENSATION_FAILED: "failure",
  MANUAL_INTERVENTION: "unresolved",
} as const;

test.each(Object.entries(EXPECTED_GROUPS))("renders canonical state %s as %s", (state, group) => {
  render(<StateBadge state={state} />);
  expect(screen.getByText(operationStateLabel(state)!)).toHaveClass(`state-badge--${group}`);
  expect(stateGroup(state)).toBe(group);
});

test("preserves a future state as unsupported text", () => {
  render(<StateBadge state="FUTURE_STATE" />);
  expect(screen.getByText("Unsupported state: FUTURE_STATE")).toHaveClass("state-badge--unsupported");
});

test("unknown never uses failure treatment", () => {
  render(<StateBadge state="UNKNOWN" />);
  expect(screen.getByText("Outcome unknown")).toHaveClass("state-badge--unresolved");
  expect(screen.getByText("Outcome unknown")).not.toHaveClass("state-badge--failure");
});
