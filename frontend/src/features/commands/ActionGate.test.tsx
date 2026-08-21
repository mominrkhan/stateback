import { fireEvent, render, screen } from "@testing-library/react";
import { ActionGate } from "../../components/ActionGate";

describe("ActionGate", () => {
  it("renders only exact backend-returned known commands", () => {
    const onAction = vi.fn(); render(<ActionGate availableActions={["approve", "verify"]} onAction={onAction} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve operation" }));
    expect(onAction).toHaveBeenCalledWith("approve");
    expect(screen.getByRole("button", { name: "Request verification" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /compensation/i })).not.toBeInTheDocument();
  });
  it("shows a safe diagnostic but no control for unknown action keys", () => {
    const onAction = vi.fn(); render(<ActionGate availableActions={["force_success\nsecret"]} onAction={onAction} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("force_success�secret"); expect(onAction).not.toHaveBeenCalled();
  });
  it("disables all known command controls during unresolved work", () => {
    render(<ActionGate availableActions={["reject", "compensate"]} disabled onAction={vi.fn()} />);
    expect(screen.getAllByRole("button")).toEqual(expect.arrayContaining([expect.objectContaining({ disabled: true })]));
  });
});
