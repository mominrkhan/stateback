import type { ProviderEvidence, Reconstruction } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { Timestamp } from "../../components/Timestamp";
import { EmptyDetail } from "./detailUtils";

function Evidence({ evidence, label }: { evidence: ProviderEvidence; label: string }) {
  return (
    <article className="evidence-record">
      <h3>{label}: authoritative provider evidence</h3>
      <dl>
        <div><dt>Source</dt><dd>{evidence.source}</dd></div>
        <div><dt>Provider</dt><dd>{evidence.provider}</dd></div>
        <div><dt>Provider status</dt><dd>{evidence.provider_status ?? "Not recorded"}</dd></div>
        <div><dt>Observed</dt><dd><Timestamp value={evidence.observed_at} /></dd></div>
        {evidence.provider_request_id && <div><dt>Provider request ID</dt><dd><CopyableId value={evidence.provider_request_id} label="provider request ID" /></dd></div>}
        {evidence.external_operation_id && <div><dt>External operation ID</dt><dd><CopyableId value={evidence.external_operation_id} label="external operation ID" /></dd></div>}
      </dl>
      {evidence.external_resource_ids.length > 0 && (
        <ul aria-label="External resource IDs">
          {evidence.external_resource_ids.map((id) => <li key={id}><CopyableId value={id} label="external resource ID" /></li>)}
        </ul>
      )}
      <p>Provider evidence is distinct from verification and canonical operation state.</p>
    </article>
  );
}

export function EvidencePanel({ reconstruction }: { reconstruction: Reconstruction }) {
  const evidence = [
    ...reconstruction.attempts.flatMap((attempt) => attempt.evidence ? [{ key: attempt.attempt_id, label: `Execution attempt ${attempt.attempt_number}`, value: attempt.evidence }] : []),
    ...reconstruction.compensation_attempts.flatMap((attempt) => attempt.evidence ? [{ key: attempt.compensation_attempt_id, label: `Compensation attempt ${attempt.attempt_number}`, value: attempt.evidence }] : []),
  ];
  return (
    <section aria-labelledby="evidence-heading">
      <h2 id="evidence-heading">Evidence</h2>
      {evidence.length === 0 ? <EmptyDetail>No authoritative provider evidence is present.</EmptyDetail> : evidence.map((item) => (
        <Evidence key={item.key} evidence={item.value} label={item.label} />
      ))}
    </section>
  );
}
