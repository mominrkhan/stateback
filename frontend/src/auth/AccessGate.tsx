import { useEffect, useRef, useState, type FormEvent } from "react";
import { Eye, EyeOff, KeyRound, ShieldCheck } from "lucide-react";

import { useAuthSession } from "./AuthSession";

export function AccessGate() {
  const { accessMessage, beginSession } = useAuthSession();
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => headingRef.current?.focus(), []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch("/v1/operator/operations?limit=1", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.status === 401) {
        setError("That access token was not accepted.");
        return;
      }
      if (!response.ok) {
        setError("Stateback could not verify access. Try again.");
        return;
      }
      if (beginSession(token)) setToken("");
    } catch {
      setError("Stateback could not be reached. Check the deployment and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main id="main-content" className="login" aria-labelledby="access-heading">
      <div className="login__brand"><span className="stateback-mark" aria-hidden="true"><i /><i /><i /></span><span>Stateback</span></div>
      <div className="login__heading-icon"><ShieldCheck size={22} aria-hidden="true" /></div>
      <h1 ref={headingRef} id="access-heading" data-page-heading tabIndex={-1}>Sign in to Stateback</h1>
      <p>Authenticate with the access token issued by your Stateback deployment.</p>
      {accessMessage && <p role="alert">{accessMessage}</p>}
      {error && <p className="login__error" role="alert">{error}</p>}
      <form onSubmit={(event) => void submit(event)} aria-busy={submitting}>
        <label htmlFor="access-token"><KeyRound size={14} aria-hidden="true" /> Access token</label>
        <span>
          <input
            id="access-token"
            type={showToken ? "text" : "password"}
            autoComplete="off"
            required
            disabled={submitting}
            value={token}
            onChange={(event) => setToken(event.currentTarget.value)}
          />
          <button
            type="button"
            aria-label={showToken ? "Hide token" : "Show token"}
            aria-controls="access-token"
            aria-pressed={showToken}
            disabled={submitting}
            onClick={() => setShowToken((shown) => !shown)}
          >
            {showToken ? <><EyeOff size={15} /> Hide</> : <><Eye size={15} /> Show</>}
          </button>
        </span>
        <button className="primitive-button primitive-button--primary" type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
