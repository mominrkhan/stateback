import { act, fireEvent, render, screen } from "@testing-library/react";

import { AuthSession, consumeBootstrapToken, restoreDevBootstrapToken, useAuthSession } from "./AuthSession";

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

test("consumes a valid dev bootstrap and restores it for a same-tab refresh", () => {
  const token = "a".repeat(43);
  window.history.replaceState(null, "", `/operations#stateback-bootstrap=${token}`);
  const bootstrap = consumeBootstrapToken();
  render(<AuthSession initialToken={bootstrap}><Probe /></AuthSession>);

  expect(window.location.hash).toBe("");
  expect(window.location.pathname).toBe("/operations");
  expect(screen.getByLabelText("token")).toHaveTextContent(token);
  expect(localStorage).toHaveLength(0);
  expect(sessionStorage).toHaveLength(1);
  expect(restoreDevBootstrapToken()).toBe(token);
});

test("logout and unauthorized clear only the stored dev bootstrap credential", () => {
  const token = "b".repeat(43);
  window.history.replaceState(null, "", `/#stateback-bootstrap=${token}`);
  const bootstrap = consumeBootstrapToken();
  render(<AuthSession initialToken={bootstrap}><Probe /></AuthSession>);
  expect(restoreDevBootstrapToken()).toBe(token);
  fireEvent.click(screen.getByText("401"));
  expect(restoreDevBootstrapToken()).toBeNull();
});

test("clears malformed bootstrap fragments and keeps authentication closed", () => {
  sessionStorage.setItem("stateback.dev-bootstrap", "c".repeat(43));
  window.history.replaceState(null, "", "/#stateback-bootstrap=not+a+dev+token");
  const bootstrap = consumeBootstrapToken();
  render(<AuthSession initialToken={bootstrap}><Probe /></AuthSession>);

  expect(bootstrap).toBeNull();
  expect(window.location.hash).toBe("");
  expect(screen.getByLabelText("token")).toHaveTextContent("");
  expect(restoreDevBootstrapToken()).toBeNull();
});
