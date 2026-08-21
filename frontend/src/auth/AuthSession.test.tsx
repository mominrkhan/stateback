import { act, fireEvent, render, screen } from "@testing-library/react";

import { AuthSession, useAuthSession } from "./AuthSession";

function Probe() {
  const session = useAuthSession();
  const capturedGeneration = 0;
  return (
    <>
      <output aria-label="token">{session.getAccessToken()}</output>
      <output aria-label="generation">{session.sessionGeneration}</output>
      <output aria-label="current-generation">{String(session.isCurrentGeneration(capturedGeneration))}</output>
      <button onClick={() => session.beginSession("  opaque  ")}>login</button>
      <button onClick={() => session.clearSession("unauthorized")}>401</button>
      <button onClick={() => {
        const controller = session.createAbortController();
        controller.signal.addEventListener("abort", () => document.body.dataset.aborted = "yes");
      }}>request</button>
    </>
  );
}

test("keeps the opaque token exact in memory and aborts on unauthorized", () => {
  render(<AuthSession><Probe /></AuthSession>);
  fireEvent.click(screen.getByText("login"));
  expect(screen.getByLabelText("token").textContent).toBe("  opaque  ");
  fireEvent.click(screen.getByText("request"));
  act(() => fireEvent.click(screen.getByText("401")));
  expect(document.body.dataset.aborted).toBe("yes");
  expect(screen.getByLabelText("token")).toHaveTextContent("");
  expect(screen.getByLabelText("generation")).toHaveTextContent("1");
  expect(screen.getByLabelText("current-generation")).toHaveTextContent("false");
  expect(localStorage).toHaveLength(0);
  expect(sessionStorage).toHaveLength(0);
});
