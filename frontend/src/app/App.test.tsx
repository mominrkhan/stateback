import { fireEvent, screen, waitFor } from "@testing-library/react";

import { renderWithSession } from "../test/render";
import { useAuthSession } from "../auth/AuthSession";
import { App } from "./App";

function login(token = " opaque token ") {
  fireEvent.change(screen.getByLabelText("Deployment access token"), { target: { value: token } });
  fireEvent.click(screen.getByRole("button", { name: "Open operator console" }));
}

beforeEach(() => window.history.replaceState(null, "", "/"));

test("root canonicalizes with replaceState after access and focuses operations", async () => {
  const replace = vi.spyOn(window.history, "replaceState");
  renderWithSession(<App />);
  login();
  const heading = await screen.findByRole("heading", { name: "Operations" });
  await waitFor(() => expect(window.location.pathname).toBe("/operations"));
  expect(replace).toHaveBeenCalledWith(null, "", "/operations");
  expect(heading).toHaveFocus();
});

test("supports navigation and browser history", async () => {
  window.history.replaceState(null, "", "/operations");
  renderWithSession(<App />);
  login();
  fireEvent.click(await screen.findByRole("link", { name: "Approvals" }));
  expect(await screen.findByRole("heading", { name: "Approvals" })).toHaveFocus();
  window.history.back();
  window.dispatchEvent(new PopStateEvent("popstate"));
  expect(await screen.findByRole("heading", { name: "Operations" })).toHaveFocus();
});

test("renders invalid operation paths without making identity assumptions", async () => {
  window.history.replaceState(null, "", "/operations/%2F");
  renderWithSession(<App />);
  login();
  expect(await screen.findByRole("heading", { name: "Page not found" })).toHaveFocus();
});

test("logout purges the shell, replaces history, and focuses access", async () => {
  window.history.replaceState(null, "", "/operations");
  renderWithSession(<App />);
  login();
  fireEvent.click(await screen.findByRole("button", { name: "Log out" }));
  const access = await screen.findByRole("heading", { name: "Stateback Operator access" });
  expect(window.location.pathname).toBe("/");
  expect(screen.queryByRole("navigation", { name: "Operator navigation" })).not.toBeInTheDocument();
  expect(access).toHaveFocus();
});

test("unauthorized clears the session and reports no identity or lifecycle claim", async () => {
  function UnauthorizedTrigger() {
    const session = useAuthSession();
    return <button onClick={() => session.clearSession("unauthorized")}>simulate 401</button>;
  }

  window.history.replaceState(null, "", "/operations");
  renderWithSession(<><App /><UnauthorizedTrigger /></>);
  login();
  fireEvent.click(await screen.findByRole("button", { name: "simulate 401" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Session expired or token rejected");
  expect(screen.getByRole("heading", { name: "Stateback Operator access" })).toHaveFocus();
  expect(screen.queryByText("Operations")).not.toBeInTheDocument();
});

test("access token visibility is deliberate and value is not remembered", async () => {
  renderWithSession(<App />);
  const input = screen.getByLabelText("Deployment access token");
  expect(input).toHaveAttribute("type", "password");
  fireEvent.click(screen.getByRole("button", { name: "Show token" }));
  expect(input).toHaveAttribute("type", "text");
  login("token-value");
  fireEvent.click(await screen.findByRole("button", { name: "Log out" }));
  expect(screen.getByLabelText("Deployment access token")).toHaveValue("");
});
