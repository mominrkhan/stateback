import { useCallback, useEffect, useState } from "react";

import type { OperatorApi } from "./api";
import type { Operation, Reconstruction } from "./types";
import { isKnownState } from "./types";
import "./styles.css";

const ACTIONS: Record<string, string> = {
  approve: "Approve operation",
  reject: "Reject operation",
  verify: "Request verification",
  compensate: "Start compensation",
  retry_compensation: "Retry compensation",
  escalate_compensation: "Escalate",
};

function timestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? "Invalid timestamp" : parsed.toISOString();
}

export function StateBadge({ state }: { state: string }) {
  if (!isKnownState(state)) {
    return <span className="badge unsupported">Unsupported state: {state}</span>;
  }
  const uncertain = ["UNKNOWN", "VERIFYING", "MANUAL_INTERVENTION", "COMPENSATION_UNKNOWN"].includes(state);
  return <span className={`badge ${uncertain ? "uncertain" : state.toLowerCase()}`}>{state.replaceAll("_", " ")}</span>;
}

export function App({ api }: { api: OperatorApi }) {
  const [operations, setOperations] = useState<Operation[]>([]);
  const [detail, setDetail] = useState<Reconstruction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      setOperations(await api.list());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load operations");
    }
  }, [api]);

  useEffect(() => void load(), [load]);

  async function select(operation: Operation) {
    try {
      setError(null);
      setDetail(await api.reconstruct(operation.operation_id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load operation");
    }
  }

  async function act(action: string, label: string) {
    if (!detail || !window.confirm(`${label} for operation ${detail.operation.operation_id}?`)) return;
    const reason = window.prompt("Operator reason")?.trim();
    if (!reason) return;
    setPending(true);
    setError(null);
    try {
      await api.control(detail.operation, action, reason);
      setDetail(await api.reconstruct(detail.operation.operation_id));
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Action was not accepted");
    } finally {
      setPending(false);
    }
  }

  return (
    <main>
      <header>
        <p className="eyebrow">TRANSACTIONS FOR AI AGENTS</p>
        <h1>Stateback Operator</h1>
        <p>Authoritative operation state, recovery evidence, and deliberate controls.</p>
      </header>
      {error && <div role="alert" className="error">{error}</div>}
      <div className="layout">
        <section aria-labelledby="operations-heading">
          <div className="section-heading">
            <h2 id="operations-heading">Operations</h2>
            <button onClick={() => void load()}>Refresh</button>
          </div>
          <ul className="operation-list">
            {operations.map((operation) => (
              <li key={operation.operation_id}>
                <button className="operation-row" onClick={() => void select(operation)}>
                  <span>{operation.intent.effect.provider} / {operation.intent.effect.action}</span>
                  <StateBadge state={operation.state} />
                  <code>{operation.operation_id}</code>
                </button>
              </li>
            ))}
          </ul>
        </section>
        <section aria-labelledby="detail-heading" className="detail">
          <h2 id="detail-heading">Operation detail</h2>
          {!detail ? <p>Select an operation to inspect its durable history.</p> : (
            <>
              <StateBadge state={detail.operation.state} />
              <dl>
                <dt>Operation</dt><dd><code>{detail.operation.operation_id}</code></dd>
                <dt>Version</dt><dd>{detail.operation.version}</dd>
                <dt>Updated (UTC)</dt><dd><time dateTime={detail.operation.updated_at}>{timestamp(detail.operation.updated_at)}</time></dd>
              </dl>
              <div className="actions" aria-label="Available operator actions">
                {detail.available_actions.flatMap((key) => {
                  const label = ACTIONS[key];
                  return label ? [(
                    <button key={key} className="danger" disabled={pending} onClick={() => void act(key, label)}>
                      {pending ? "Waiting for server…" : label}
                    </button>
                  )] : [];
                })}
              </div>
              <h3>Durable timeline</h3>
              <ol className="timeline">
                {detail.audit.map((event) => (
                  <li key={event.audit_event_id}>
                    <strong>{event.event_type}</strong>
                    <span>{event.reason_code}</span>
                    <time dateTime={event.created_at}>{timestamp(event.created_at)}</time>
                    {event.correlation_id && <code>{event.correlation_id}</code>}
                  </li>
                ))}
              </ol>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
