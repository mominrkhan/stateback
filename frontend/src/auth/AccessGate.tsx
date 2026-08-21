import { useEffect, useRef, useState, type FormEvent } from "react";

import { useAuthSession } from "./AuthSession";

export function AccessGate() {
  const { accessMessage, beginSession } = useAuthSession();
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => headingRef.current?.focus(), []);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (beginSession(token)) setToken("");
  }

  return (
    <main id="main-content" className="login" aria-labelledby="access-heading">
      <h1 ref={headingRef} id="access-heading" tabIndex={-1}>Stateback Operator access</h1>
      <p>Enter the opaque access token supplied by your Stateback deployment administrator.</p>
      {accessMessage && <p role="alert">{accessMessage}</p>}
      <form onSubmit={submit}>
        <label htmlFor="access-token">Deployment access token</label>
        <span>
          <input
            id="access-token"
            type={showToken ? "text" : "password"}
            autoComplete="off"
            required
            value={token}
            onChange={(event) => setToken(event.currentTarget.value)}
          />
          <button
            type="button"
            aria-controls="access-token"
            aria-pressed={showToken}
            onClick={() => setShowToken((shown) => !shown)}
          >
            {showToken ? "Hide token" : "Show token"}
          </button>
        </span>
        <button type="submit">Open operator console</button>
      </form>
    </main>
  );
}
