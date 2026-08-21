import type { Reconstruction } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { Timestamp } from "../../components/Timestamp";
import { EmptyDetail, Principal } from "./detailUtils";

export function CompensationPanel({ reconstruction }: { reconstruction: Reconstruction }) {
  const { compensation, compensation_attempts: attempts } = reconstruction;
  return (
    <section aria-labelledby="compensation-heading">
      <h2 id="compensation-heading">Compensation</h2>
      {!compensation ? <EmptyDetail>No compensation exists for this operation.</EmptyDetail> : (
        <article>
          <dl>
            <div><dt>Compensation ID</dt><dd><CopyableId value={compensation.compensation_id} label="compensation ID" /></dd></div>
            <div><dt>Kind</dt><dd>{compensation.kind}</dd></div>
            <div><dt>Compensation state</dt><dd>{compensation.state}</dd></div>
            <div><dt>Version</dt><dd>{compensation.version}</dd></div>
            <div><dt>Intent digest</dt><dd><CopyableId value={compensation.intent_digest} label="compensation intent digest" /></dd></div>
            <div><dt>Requested by</dt><dd><Principal principal={compensation.requested_by} /></dd></div>
            <div><dt>Created</dt><dd><Timestamp value={compensation.created_at} /></dd></div>
            <div><dt>Updated</dt><dd><Timestamp value={compensation.updated_at} /></dd></div>
          </dl>
          <p>Compensation is a separate side effect and does not erase the original operation history.</p>
        </article>
      )}
      <h3>Compensation attempts</h3>
      {attempts.length === 0 ? <EmptyDetail>No compensation attempts are present.</EmptyDetail> : (
        <ol>
          {attempts.map((attempt) => (
            <li key={attempt.compensation_attempt_id}>
              <CopyableId value={attempt.compensation_attempt_id} label="compensation attempt ID" />
              <p>Attempt {attempt.attempt_number}; state {attempt.state}; outcome {attempt.outcome ?? "not recorded"}</p>
              <Timestamp value={attempt.started_at} />
              {attempt.completed_at && <> — <Timestamp value={attempt.completed_at} /></>}
              {attempt.error && <p role="status">Normalized error: {attempt.error.kind} / {attempt.error.code}. {attempt.error.message}</p>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
