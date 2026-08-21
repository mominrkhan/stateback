import { fireEvent, render, screen } from "@testing-library/react";

import { OperatorReasonField, validateOperatorReason } from "./OperatorReasonField";

test.each([
  ["approve", 500],
  ["reject", 500],
  ["verify", 200],
  ["compensate", 200],
  ["retry_compensation", 200],
  ["escalate_compensation", 200],
])("uses the contract limit for %s", (action, maxLength) => {
  expect(validateOperatorReason(action, "accepted reason").maxLength).toBe(maxLength);
});

test("normalizes once and reports empty, non-ASCII, and over-limit reasons", () => {
  expect(validateOperatorReason("approve", "  accepted reason  ")).toMatchObject({
    normalized: "accepted reason",
    error: null,
  });
  expect(validateOperatorReason("approve", "   ").error).toBe("Enter a reason.");
  expect(validateOperatorReason("approve", "café").error).toBe("Use ASCII characters only.");
  expect(validateOperatorReason("verify", "x".repeat(201)).error).toContain("200");
});

test("associates visible validation with the reason field", () => {
  const onChange = vi.fn();
  render(<OperatorReasonField actionKey="verify" value="" onChange={onChange} showValidation />);
  const field = screen.getByLabelText("Operator reason");
  expect(field).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByText("Enter a reason.")).toBeVisible();
  fireEvent.change(field, { target: { value: "operator requested" } });
  expect(onChange).toHaveBeenCalledWith("operator requested");
});
