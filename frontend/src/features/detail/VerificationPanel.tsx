import type { Reconstruction } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { Timestamp } from "../../components/Timestamp";
import { EmptyDetail } from "./detailUtils";

export function VerificationPanel({ reconstruction }: { reconstruction: Reconstruction }) {
  return (
    <section aria-labelledby="verification-heading">
      <h2 id="verification-heading">Verification and reconciliation</h2>
      <p role="status">Verification records are not available on the accepted v1 reconstruction wire. No verification result is inferred.</p>
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
