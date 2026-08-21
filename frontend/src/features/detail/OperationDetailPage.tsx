import { useEffect, useRef, type ReactNode } from "react";

import type { Reconstruction } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { StateBadge } from "../../components/StateBadge";
import { Timestamp } from "../../components/Timestamp";
import { AttemptsPanel } from "./AttemptsPanel";
import { AuditTimeline } from "./AuditTimeline";
import { CompensationPanel } from "./CompensationPanel";
import { EvidencePanel } from "./EvidencePanel";
import { Principal } from "./detailUtils";
import { SummaryPanel } from "./SummaryPanel";
import { VerificationPanel } from "./VerificationPanel";

export interface OperationDetailPageProps {
  reconstruction: Reconstruction;
  actions?: ReactNode;
  advisory?: ReactNode;
}

export function OperationDetailPage({ reconstruction, actions, advisory }: OperationDetailPageProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const { operation } = reconstruction;
  const effect = operation.intent.effect;
  const correlations = Array.from(new Set([
    ...reconstruction.attempts.map((attempt) => attempt.correlation_id),
    ...reconstruction.audit.map((event) => event.correlation_id),
  ].filter((value): value is string => value !== null)));
  const latestReason = reconstruction.audit.at(-1)?.reason_code ?? "Not recorded";
  const actionBasis = reconstruction.available_actions.join(", ") || "None";

  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, [operation.operation_id]);

  return (
    <article className="operation-detail">
      <header>
        <p>Operation reconstruction</p>
        <h1 ref={headingRef} data-page-heading tabIndex={-1}>Operation detail</h1>
        <div className="operation-detail__critical" aria-label="Critical operation status and controls">
          <div className="operation-detail__critical-state"><StateBadge state={operation.state} /></div>
          <dl className="operation-detail__critical-id">
            <div><dt>Operation ID</dt><dd><CopyableId value={operation.operation_id} label="operation ID" /></dd></div>
          </dl>
          <dl className="operation-detail__critical-basis">
            <div><dt>Current reason</dt><dd>{latestReason}</dd></div>
            <div><dt>Backend action basis</dt><dd>{actionBasis}</dd></div>
          </dl>
          {actions && <div className="operation-detail__critical-actions" aria-label="Available operator actions">{actions}</div>}
        </div>
        <dl className="operation-detail__secondary-metadata">
          <div><dt>Version</dt><dd>{operation.version}</dd></div>
          <div><dt>Effect</dt><dd>{effect.provider} / {effect.action} / {effect.version}</dd></div>
          <div><dt>Requester</dt><dd><Principal principal={operation.intent.requester} /></dd></div>
          <div><dt>Created</dt><dd><Timestamp value={operation.created_at} /></dd></div>
          <div><dt>Updated</dt><dd><Timestamp value={operation.updated_at} /></dd></div>
        </dl>
        {correlations.length > 0 && (
          <ul className="operation-detail__correlations" aria-label="Correlation identifiers">
            {correlations.map((id) => <li key={id}><CopyableId value={id} label="correlation ID" /></li>)}
          </ul>
        )}
      </header>
      <nav className="operation-detail__section-navigation" aria-label="Operation detail sections">
        <a href="#summary-heading">Summary</a>
        <a href="#evidence-heading">Evidence</a>
        <a href="#attempts-heading">Attempts</a>
        <a href="#verification-heading">Verification</a>
        <a href="#compensation-heading">Compensation</a>
        <a href="#audit-heading">Audit</a>
      </nav>
      <SummaryPanel reconstruction={reconstruction} />
      <EvidencePanel reconstruction={reconstruction} />
      <AttemptsPanel reconstruction={reconstruction} />
      <VerificationPanel reconstruction={reconstruction} />
      <CompensationPanel reconstruction={reconstruction} />
      <AuditTimeline reconstruction={reconstruction} />
      {advisory}
    </article>
  );
}
