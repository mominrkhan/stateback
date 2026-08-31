import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";

import { ConfirmationDialog } from "./ConfirmationDialog";

function Harness({ pending = false }: { pending?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open confirmation</button>
      <ConfirmationDialog
        open={open}
        title="Confirm compensation"
        description="This command may have an ambiguous provider outcome."
        confirmLabel="Start compensation"
        pending={pending}
        onCancel={() => setOpen(false)}
        onConfirm={() => undefined}
      >
        <label htmlFor="reason">Reason</label>
        <input id="reason" />
      </ConfirmationDialog>
    </>
  );
}

test("names the modal, focuses its heading, closes on Escape, and restores focus", async () => {
  render(<Harness />);
  const trigger = screen.getByRole("button", { name: "Open confirmation" });
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "Confirm compensation" });
  expect(dialog).toHaveAccessibleDescription("This command may have an ambiguous provider outcome.");
  await waitFor(() => expect(screen.getByRole("heading", { name: "Confirm compensation" })).toHaveFocus());
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await waitFor(() => expect(trigger).toHaveFocus());
});

test("provides focusable controls inside the Base UI modal", () => {
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Open confirmation" }));
  const firstField = screen.getByLabelText("Reason");
  const confirm = screen.getByRole("button", { name: "Start compensation" });
  const dialog = screen.getByRole("dialog");
  expect(dialog).toContainElement(firstField);
  expect(dialog).toContainElement(confirm);
  expect(screen.getByRole("button", { name: "Close dialog" })).toBeInTheDocument();
});

test("announces pending state and prevents dismissal", () => {
  render(<Harness pending />);
  fireEvent.click(screen.getByRole("button", { name: "Open confirmation" }));
  const dialog = screen.getByRole("dialog");
  expect(screen.getByRole("status")).toHaveTextContent("Submitting command…");
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(dialog).toBeInTheDocument();
});
