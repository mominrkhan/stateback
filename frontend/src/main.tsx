import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { createOperatorApi } from "./api";

function Root() {
  const [token, setToken] = useState("");
  if (!token) {
    return (
      <main className="login">
        <h1>Stateback Operator</h1>
        <form onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          setToken(String(data.get("token") ?? ""));
        }}>
          <label htmlFor="token">Deployment access token</label>
          <input id="token" name="token" type="password" autoComplete="off" required />
          <button type="submit">Open control plane</button>
        </form>
      </main>
    );
  }
  return <App api={createOperatorApi("", () => token)} />;
}

createRoot(document.getElementById("root")!).render(<StrictMode><Root /></StrictMode>);
