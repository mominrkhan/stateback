import type { Reconstruction } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { Timestamp } from "../../components/Timestamp";
import { EmptyDetail, Principal } from "./detailUtils";

export function AuditTimeline({ reconstruction }: { reconstruction: Reconstruction }) {
  return (
    <section aria-labelledby="audit-heading">
      <h2 id="audit-heading">Durable audit</h2>
      {reconstruction.audit.length === 0 ? <EmptyDetail>No audit events are present.</EmptyDetail> : (
        <ol className="audit-timeline">
          {reconstruction.audit.map((event) => (
            <li key={event.audit_event_id}>
              <h3>Sequence {event.sequence}: {event.event_type}</h3>
              <dl>
                <div><dt>Audit event ID</dt><dd><CopyableId value={event.audit_event_id} label="audit event ID" /></dd></div>
                <div><dt>Reason code</dt><dd>{event.reason_code}</dd></div>
                <div><dt>Transition</dt><dd>{event.from_state ?? "None"} → {event.to_state ?? "None"}</dd></div>
                <div><dt>Operation version</dt><dd>{event.operation_version}</dd></div>
                <div><dt>Actor</dt><dd><Principal principal={event.actor} /></dd></div>
                {event.correlation_id && <div><dt>Correlation ID</dt><dd><CopyableId value={event.correlation_id} label="correlation ID" /></dd></div>}
                <div><dt>Recorded</dt><dd><Timestamp value={event.created_at} /></dd></div>
              </dl>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
