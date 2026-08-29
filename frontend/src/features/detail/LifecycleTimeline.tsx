import type { AuditEvent, Reconstruction } from "../../api/types";
import { Timestamp } from "../../components/Timestamp";

function eventPresentation(event: AuditEvent): { symbol: string; label: string; detail: string } {
  if (event.event_type === "operation.created.v1") return { symbol: "✓", label: "Intent recorded", detail: "Stateback durably recorded the requested action." };
  if (event.event_type === "policy.evaluated.v1") return { symbol: "✓", label: "Policy evaluated", detail: "The configured policy evaluated this intent." };
  if (event.event_type === "approval.requested.v1") return { symbol: "•", label: "Approval requested", detail: "The operation was held for an approval decision." };
  if (event.event_type === "approval.decided.v1") return { symbol: event.to_state === "READY" ? "✓" : "•", label: event.to_state === "READY" ? "Approval granted" : "Approval decided", detail: `Durable reason: ${event.reason_code}.` };
  if (event.event_type === "execution.attempt_started.v1") return { symbol: "•", label: "Execution started", detail: "A provider execution attempt was durably started." };
  if (event.event_type === "execution.evidence_recorded.v1" && event.to_state === "UNKNOWN") return { symbol: "?", label: "Provider outcome became uncertain", detail: "The durable evidence did not prove whether the external action was applied." };
  if (event.event_type === "execution.evidence_recorded.v1") return { symbol: "✓", label: "Provider evidence recorded", detail: `The operation moved to ${event.to_state ?? "its recorded state"}.` };
  if (event.event_type === "verification.started.v1") return { symbol: "↻", label: "Verification started", detail: "Stateback began checking provider evidence." };
  if (event.event_type === "verification.completed.v1") return { symbol: "✓", label: "Verification completed", detail: `Durable reason: ${event.reason_code}.` };
  if (event.event_type === "reconciliation.decided.v1") return { symbol: "✓", label: event.to_state === "SUCCEEDED" ? "Reconciled as succeeded" : event.to_state === "FAILED" ? "Reconciled as failed" : "Reconciliation decided", detail: `The durable record moved to ${event.to_state ?? "its recorded state"}.` };
  if (event.event_type === "compensation.requested.v1") return { symbol: "•", label: "Compensation requested", detail: "A separate compensating effect was durably requested." };
  if (event.event_type === "compensation.attempted.v1") return { symbol: "•", label: "Compensation attempted", detail: "A provider compensation attempt was started." };
  if (event.event_type === "compensation.result.v1") return { symbol: event.to_state === "COMPENSATION_UNKNOWN" ? "?" : "✓", label: event.to_state === "COMPENSATION_UNKNOWN" ? "Compensation outcome uncertain" : "Compensation result recorded", detail: `The operation moved to ${event.to_state ?? "its recorded state"}.` };
  return { symbol: "•", label: "Lifecycle record", detail: `${event.event_type} · ${event.reason_code}` };
}

export function LifecycleTimeline({ reconstruction }: { reconstruction: Reconstruction }) {
  const events = [...reconstruction.audit].sort((left, right) => left.sequence - right.sequence);
  return (
    <section aria-labelledby="lifecycle-heading" className="lifecycle-panel">
      <div className="section-heading"><div><p className="eyebrow">DURABLE HISTORY</p><h2 id="lifecycle-heading">Lifecycle</h2></div><a href="#audit-heading">View raw audit</a></div>
      {events.length === 0 ? <p className="detail-empty">No durable lifecycle events are present.</p> : <ol className="lifecycle-timeline">{events.map((event) => { const item = eventPresentation(event); return <li key={event.audit_event_id}><span className="lifecycle-timeline__symbol" aria-hidden="true">{item.symbol}</span><div><strong>{item.label}</strong><p>{item.detail}</p><Timestamp value={event.created_at} /></div></li>; })}</ol>}
    </section>
  );
}
