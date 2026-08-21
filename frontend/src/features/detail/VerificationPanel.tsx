import type { Reconstruction } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { Timestamp } from "../../components/Timestamp";
import { EmptyDetail } from "./detailUtils";

export function VerificationPanel({ reconstruction }: { reconstruction: Reconstruction }) {
  return (
    <section aria-labelledby="verification-heading">
      <h2 id="verification-heading">Verification and reconciliation</h2>
      {reconstruction.verifications.length === 0 ? <EmptyDetail>No verification record is present.</EmptyDetail> : (
        <ol aria-label="Verification history">
          {reconstruction.verifications.map(({ request, result }) => (
            <li key={request.verification_id}>
              <CopyableId value={request.verification_id} label="verification ID" />
              <p>{request.target}: {request.effect.provider} / {request.effect.action} / {request.effect.version}</p>
              {request.target_attempt_id && <p>Attempt <CopyableId value={request.target_attempt_id} label="target attempt ID" /></p>}
              {result ? (
                <>
                  <p>Outcome: {result.outcome}</p>
                  <p>Evidence: {result.evidence.provider} — {result.evidence.provider_status ?? "Not recorded"}</p>
                  {result.error && <p>Error: {result.error.code}</p>}
                  <Timestamp value={result.completed_at} />
                </>
              ) : <p role="status">Verification result is pending.</p>}
              <Timestamp value={request.requested_at} />
            </li>
          ))}
        </ol>
      )}
      <h3>Reconciliation decisions</h3>
      {reconstruction.reconciliations.length === 0 ? <EmptyDetail>No reconciliation decision is present.</EmptyDetail> : (
        <ol>
          {reconstruction.reconciliations.map((item) => (
            <li key={item.reconciliation_decision_id}>
              <CopyableId value={item.reconciliation_decision_id} label="reconciliation decision ID" />
              <p>{item.decision.action}: {item.decision.reason_code}</p>
              {item.verification_id && <p>Verification <CopyableId value={item.verification_id} label="verification ID" /></p>}
              <Timestamp value={item.created_at} />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
