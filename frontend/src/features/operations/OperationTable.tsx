import type { MouseEvent } from "react";

import type { JsonValue, Operation } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { StateBadge } from "../../components/StateBadge";
import { Timestamp } from "../../components/Timestamp";
import { actionLabel, providerLabel, requesterLabel } from "../../presentation/labels";

function resourceLabel(operation: Operation): string | null {
  if (operation.intent.effect.provider !== "github") return null;
  const argumentsValue = operation.intent.arguments;
  if (typeof argumentsValue !== "object" || argumentsValue === null || Array.isArray(argumentsValue)) return null;
  const owner = argumentsValue.owner;
  const repo = argumentsValue.repo;
  return typeof owner === "string" && typeof repo === "string" ? `${owner}/${repo}` : null;
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
          <tr><th scope="col">Status</th><th scope="col">Action</th><th scope="col">Provider</th><th scope="col">Requester / Agent</th><th scope="col">Updated</th></tr>
        </thead>
        <tbody>
          {operations.map((operation) => {
            const href = `/operations/${encodeURIComponent(operation.operation_id)}`;
            return (
              <tr key={operation.operation_id}>
                <td data-label="Status"><StateBadge state={operation.state} /></td>
                <td data-label="Action">
                  <a
                    href={href}
                    aria-label={`${actionLabel(operation.intent.effect)}; operation ${operation.operation_id}`}
                    onClick={(event) => follow(event, operation.operation_id)}
                  >
                    {actionLabel(operation.intent.effect)}
                  </a>
                  {resourceLabel(operation) && <small className="operation-table__resource">{resourceLabel(operation)}</small>}
                  <CopyableId value={operation.operation_id} label="operation ID" />
                </td>
                <td data-label="Provider">{providerLabel(operation.intent.effect.provider)}</td>
                <td data-label="Requester / Agent">{requesterLabel(operation.intent.requester)}</td>
                <td data-label="Updated"><Timestamp value={operation.updated_at} relative /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
