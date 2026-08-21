import type { MouseEvent } from "react";

import type { Operation } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { StateBadge } from "../../components/StateBadge";
import { Timestamp } from "../../components/Timestamp";

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
        {operations.map((operation) => (
          <li key={operation.operation_id}>
            <a
              href={`/operations/${encodeURIComponent(operation.operation_id)}`}
              aria-label={`${operation.intent.effect.provider} / ${operation.intent.effect.action} / ${operation.intent.effect.version}; operation ${operation.operation_id}`}
              aria-current={selectedOperationId === operation.operation_id ? "true" : undefined}
              aria-disabled={disabled || undefined}
              onClick={(event) => {
                if (disabled) event.preventDefault();
                else follow(event, operation);
              }}
            >
              {operation.intent.effect.provider} / {operation.intent.effect.action} / {operation.intent.effect.version}
            </a>
            <StateBadge state={operation.state} />
            <CopyableId value={operation.operation_id} label="operation ID" />
            <Timestamp value={operation.created_at} />
          </li>
        ))}
      </ul>
    </section>
  );
}
