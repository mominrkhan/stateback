import type { MouseEvent } from "react";

import type { Operation } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { StateBadge } from "../../components/StateBadge";
import { Timestamp } from "../../components/Timestamp";
import { operationPresentation } from "../../presentation/operationPresentation";

interface ApprovalQueueProps {
  operations: Operation[];
  selectedOperationId: string | null;
  disabled?: boolean;
  onSelect: (operation: Operation) => void;
}

export function ApprovalQueue({ operations, selectedOperationId, disabled = false, onSelect }: ApprovalQueueProps) {
  function follow(event: MouseEvent<HTMLAnchorElement>, operation: Operation) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onSelect(operation);
  }

  return (
    <section aria-labelledby="approval-queue-heading">
      <h2 id="approval-queue-heading">Awaiting approval</h2>
      <ul className="approval-queue">
        {operations.map((operation) => {
          const view = operationPresentation(operation);
          return (
          <li key={operation.operation_id}>
            <a
              href={`/operations/${encodeURIComponent(operation.operation_id)}`}
              aria-label={`${view.action} with ${view.provider}; operation ${operation.operation_id}`}
              aria-current={selectedOperationId === operation.operation_id ? "true" : undefined}
              aria-disabled={disabled || undefined}
              onClick={(event) => {
                if (disabled) event.preventDefault();
                else follow(event, operation);
              }}
            >
              <strong>{view.action}</strong>
              <small>{view.primaryResource ? `${view.provider} · ${view.primaryResource}` : view.provider}</small>
              <small>{view.requester} · <Timestamp value={operation.created_at} relative /></small>
            </a>
            <StateBadge state={operation.state} />
            <CopyableId value={operation.operation_id} label="operation ID" />
          </li>
        )})}
      </ul>
    </section>
  );
}
