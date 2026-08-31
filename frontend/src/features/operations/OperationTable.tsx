import { createColumnHelper, tableFeatures, useTable } from "@tanstack/react-table";
import { ArrowUpRight } from "lucide-react";
import type { MouseEvent } from "react";

import type { Operation } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { StateBadge } from "../../components/StateBadge";
import { Timestamp } from "../../components/Timestamp";
import { operationPresentation } from "../../presentation/operationPresentation";

interface OperationTableProps { operations: Operation[]; onNavigate: (operationId: string) => void }
const features = tableFeatures({});
const column = createColumnHelper<typeof features, Operation>();

export function OperationTable({ operations, onNavigate }: OperationTableProps) {
  function follow(event: MouseEvent<HTMLAnchorElement>, operationId: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); onNavigate(operationId);
  }
  const columns = column.columns([
    column.display({ id: "status", header: "Status", cell: ({ row }) => <StateBadge state={row.original.state} /> }),
    column.display({ id: "action", header: "Action / resource", cell: ({ row }) => {
      const operation = row.original; const view = operationPresentation(operation); const href = `/operations/${encodeURIComponent(operation.operation_id)}`;
      return <div className="operation-cell"><a href={href} aria-label={`${view.action}; operation ${operation.operation_id}`} onClick={(event) => follow(event, operation.operation_id)}><strong>{view.action}</strong><ArrowUpRight size={14} aria-hidden="true" /></a>{view.primaryResource && <small>{view.provider} · {view.primaryResource}</small>}{view.secondaryResource && <small>{view.secondaryResource}</small>}<CopyableId value={operation.operation_id} label="operation ID" /></div>;
    } }),
    column.display({ id: "requester", header: "Requester", cell: ({ row }) => operationPresentation(row.original).requester }),
    column.display({ id: "updated", header: "Updated", cell: ({ row }) => <Timestamp value={row.original.updated_at} relative /> }),
  ]);
  const table = useTable({ data: operations, columns, features });
  return <div className="operation-table-scroll" tabIndex={0} aria-label="Operations table region"><table className="operation-table"><caption className="visually-hidden">Backend-ordered Stateback operations</caption><thead>{table.getHeaderGroups().map((group) => <tr key={group.id}>{group.headers.map((header) => <th key={header.id} scope="col">{header.isPlaceholder ? null : <table.FlexRender header={header} />}</th>)}</tr>)}</thead><tbody>{table.getRowModel().rows.map((row) => <tr key={row.original.operation_id}>{row.getAllCells().map((cell) => <td key={cell.id} data-label={String(cell.column.columnDef.header)}><table.FlexRender cell={cell} /></td>)}</tr>)}</tbody></table></div>;
}
