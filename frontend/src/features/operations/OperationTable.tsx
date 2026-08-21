import type { MouseEvent } from "react";

import type { EffectRef, Operation } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { StateBadge } from "../../components/StateBadge";
import { Timestamp } from "../../components/Timestamp";

export function effectLabel(effect: EffectRef): string {
  if (effect.provider === "github" && effect.action === "create_issue" && effect.version === "v1") {
    return "GitHub · Create issue";
  }
  return `${effect.provider} · ${effect.action}`;
}

interface OperationTableProps {
  operations: Operation[];
  onNavigate: (operationId: string) => void;
}

export function OperationTable({ operations, onNavigate }: OperationTableProps) {
  function follow(event: MouseEvent<HTMLAnchorElement>, operationId: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onNavigate(operationId);
  }

  return (
    <div className="operation-table-scroll" tabIndex={0} aria-label="Operations table region">
      <table className="operation-table">
        <caption className="visually-hidden">Backend-ordered Stateback operations</caption>
        <thead>
          <tr><th scope="col">Effect</th><th scope="col">State</th><th scope="col">Operation ID</th><th scope="col">Created (UTC)</th></tr>
        </thead>
        <tbody>
          {operations.map((operation) => {
            const href = `/operations/${encodeURIComponent(operation.operation_id)}`;
            return (
              <tr key={operation.operation_id}>
                <td data-label="Effect">
                  <a
                    href={href}
                    aria-label={`${effectLabel(operation.intent.effect)}; operation ${operation.operation_id}`}
                    onClick={(event) => follow(event, operation.operation_id)}
                  >
                    {effectLabel(operation.intent.effect)}
                  </a>
                  <code className="operation-table__raw-effect">
                    {operation.intent.effect.provider} / {operation.intent.effect.action} / {operation.intent.effect.version}
                  </code>
                </td>
                <td data-label="State"><StateBadge state={operation.state} /></td>
                <td data-label="Operation ID"><CopyableId value={operation.operation_id} label="operation ID" /></td>
                <td data-label="Created (UTC)"><Timestamp value={operation.created_at} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
