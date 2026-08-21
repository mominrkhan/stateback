import type { ExecutionAttempt, Reconstruction } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { Timestamp } from "../../components/Timestamp";
import { EmptyDetail } from "./detailUtils";

function Attempt({ attempt }: { attempt: ExecutionAttempt }) {
  return (
    <li>
      <h3>Attempt {attempt.attempt_number}</h3>
      <dl>
        <div><dt>Attempt ID</dt><dd><CopyableId value={attempt.attempt_id} label="attempt ID" /></dd></div>
        <div><dt>Attempt state</dt><dd>{attempt.state}</dd></div>
        <div><dt>Provider outcome</dt><dd>{attempt.outcome ?? "No outcome recorded"}</dd></div>
        <div><dt>Started</dt><dd><Timestamp value={attempt.started_at} /></dd></div>
        {attempt.completed_at && <div><dt>Completed</dt><dd><Timestamp value={attempt.completed_at} /></dd></div>}
        {attempt.correlation_id && <div><dt>Correlation ID</dt><dd><CopyableId value={attempt.correlation_id} label="correlation ID" /></dd></div>}
      </dl>
      {attempt.error && (
        <p role="status">Normalized error: {attempt.error.kind} / {attempt.error.code}. {attempt.error.message}</p>
      )}
      <p>Attempt state and provider outcome do not independently establish canonical operation state.</p>
    </li>
  );
}

export function AttemptsPanel({ reconstruction }: { reconstruction: Reconstruction }) {
  return (
    <section aria-labelledby="attempts-heading">
      <h2 id="attempts-heading">Execution attempts</h2>
      {reconstruction.attempts.length === 0 ? <EmptyDetail>No execution attempts are present.</EmptyDetail> : (
        <ol>{reconstruction.attempts.map((attempt) => <Attempt key={attempt.attempt_id} attempt={attempt} />)}</ol>
      )}
    </section>
  );
}
