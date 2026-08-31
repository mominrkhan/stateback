import { useEffect, useRef, type MouseEvent, type ReactNode } from "react";
import { ArrowLeft, Braces } from "lucide-react";

import type { Reconstruction } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { StateBadge } from "../../components/StateBadge";
import { Timestamp } from "../../components/Timestamp";
import { AttemptsPanel } from "./AttemptsPanel";
import { AuditTimeline } from "./AuditTimeline";
import { CompensationPanel } from "./CompensationPanel";
import { EvidencePanel } from "./EvidencePanel";
import { LifecycleTimeline } from "./LifecycleTimeline";
import { outcomeSummary, OutcomeExplanation } from "./OutcomeExplanation";
import { Principal } from "./detailUtils";
import { SummaryPanel } from "./SummaryPanel";
import { VerificationPanel } from "./VerificationPanel";
import { effectIdentifier, providerLabel } from "../../presentation/labels";
import { operationPresentation } from "../../presentation/operationPresentation";

export interface OperationDetailPageProps {
  reconstruction: Reconstruction;
  actions?: ReactNode;
  advisory?: ReactNode;
  onNavigate?: (href: string) => void;
}

export function OperationDetailPage({ reconstruction, actions, advisory, onNavigate }: OperationDetailPageProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const { operation } = reconstruction;
  const effect = operation.intent.effect;
  const presentation = operationPresentation(operation);
  const correlations = Array.from(new Set([
    ...reconstruction.attempts.map((attempt) => attempt.correlation_id),
    ...reconstruction.audit.map((event) => event.correlation_id),
  ].filter((value): value is string => value !== null)));

  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, [operation.operation_id]);

  return (
    <article className="operation-detail">
      <header>
        <a className="operation-detail__back" href="/operations" onClick={(event: MouseEvent<HTMLAnchorElement>) => {
          if (!onNavigate || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          event.preventDefault();
          onNavigate("/operations");
        }}><ArrowLeft size={15} /> Operations</a>
        <p className="eyebrow">PROTECTED OPERATION</p>
        <h1 ref={headingRef} data-page-heading tabIndex={-1} aria-label={`${presentation.action} with ${presentation.provider}`}>{presentation.action}</h1>
        <p className="operation-detail__resource">{presentation.provider}{presentation.primaryResource ? ` · ${presentation.primaryResource}` : ""}</p>
        {presentation.secondaryResource && <p className="operation-detail__resource-context">{presentation.secondaryResource}</p>}
        <p className="operation-detail__summary">{outcomeSummary(reconstruction)}</p>
        <div className="operation-detail__critical" aria-label="Critical operation status and controls">
          <div className="operation-detail__critical-state"><StateBadge state={operation.state} /></div>
          {actions && <div className="operation-detail__critical-actions" aria-label="Available operator actions">{actions}</div>}
        </div>
        <dl className="operation-detail__secondary-metadata">
          <div><dt>Provider</dt><dd>{providerLabel(effect.provider)}</dd></div>
          <div><dt>Requester</dt><dd><Principal principal={operation.intent.requester} /></dd></div>
          <div><dt>Started</dt><dd><Timestamp value={operation.created_at} /></dd></div>
          <div><dt>Updated</dt><dd><Timestamp value={operation.updated_at} /></dd></div>
          <div><dt>Current state</dt><dd><code>{operation.state}</code></dd></div>
          <div><dt>Risk</dt><dd>{operation.risk_level}</dd></div>
        </dl>
        <details className="technical-details"><summary><Braces size={15} /> Technical details</summary><dl><div><dt>Operation ID</dt><dd><CopyableId value={operation.operation_id} label="operation ID" /></dd></div><div><dt>Contract</dt><dd>{operation.contract_version}</dd></div><div><dt>Version</dt><dd>{operation.version}</dd></div><div><dt>Effect identifier</dt><dd><code>{effectIdentifier(effect)}</code></dd></div><div><dt>Latest reason</dt><dd>{reconstruction.audit.at(-1)?.reason_code ?? "Not recorded"}</dd></div><div><dt>Backend-authorized actions</dt><dd>{reconstruction.available_actions.join(", ") || "None"}</dd></div></dl></details>
        {correlations.length > 0 && (
          <ul className="operation-detail__correlations" aria-label="Correlation identifiers">
            {correlations.map((id) => <li key={id}><CopyableId value={id} label="correlation ID" /></li>)}
          </ul>
        )}
      </header>
      <nav className="operation-detail__section-navigation" aria-label="Operation detail sections">
        <a href="#lifecycle-heading">Lifecycle</a>
        <a href="#summary-heading">Summary</a>
        <a href="#evidence-heading">Evidence</a>
        <a href="#attempts-heading">Attempts</a>
        <a href="#verification-heading">Verification</a>
        <a href="#compensation-heading">Compensation</a>
        <a href="#audit-heading">Audit</a>
      </nav>
      <OutcomeExplanation reconstruction={reconstruction} />
      <LifecycleTimeline reconstruction={reconstruction} />
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
