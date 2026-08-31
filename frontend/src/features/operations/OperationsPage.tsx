import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import type { OperatorClient } from "../../api/client";
import { ApiError } from "../../api/errors";
import { queryRead } from "../../api/queryRead";
import { OperatorQueryBoundary } from "../../app/OperatorQueryBoundary";
import { DefensiveState } from "../../components/DefensiveState";
import { Skeleton } from "../../components/Skeleton";
import {
  OperationFilters,
  OperationIdNavigation,
  parseOperationsSearch,
  serializeOperationsFilters,
  toApiFilters,
  type OperationsFilterValues,
} from "./OperationFilters";
import { OperationTable } from "./OperationTable";

export interface OperationsPageProps {
  client: OperatorClient;
  search: string;
  navigate: (href: string) => void;
  createAbortController?: () => AbortController;
  releaseAbortController?: (controller: AbortController) => void;
}

const DEFAULT_CREATE_ABORT_CONTROLLER = () => new AbortController();
const DEFAULT_RELEASE_ABORT_CONTROLLER = () => undefined;

export function OperationsPage(props: OperationsPageProps) {
  return <OperatorQueryBoundary><OperationsContent {...props} /></OperatorQueryBoundary>;
}

function OperationsContent({
  client,
  search,
  navigate,
  createAbortController = DEFAULT_CREATE_ABORT_CONTROLLER,
  releaseAbortController = DEFAULT_RELEASE_ABORT_CONTROLLER,
}: OperationsPageProps) {
  const parsed = parseOperationsSearch(search);
  const [pagination, setPagination] = useState<{ search: string; cursor?: string; history: Array<string | undefined> }>(() => ({ search, history: [] }));
  const cursor = pagination.search === search ? pagination.cursor : undefined;
  const cursorHistory = pagination.search === search ? pagination.history : [];
  const query = useQuery({
    queryKey: ["operator", "operations", search, parsed.filters, cursor ?? null],
    queryFn: ({ signal }) => queryRead(signal, createAbortController, releaseAbortController, (readSignal) => client.list(toApiFilters(parsed.filters, cursor), readSignal)),
    staleTime: 0,
  });
  const page = query.data;
  const error = query.error instanceof ApiError && query.error.status === 401
    ? null
    : query.error instanceof Error ? query.error.message : query.error ? "Unable to load operations" : null;

  function applyFilters(filters: OperationsFilterValues) {
    navigate(`/operations${serializeOperationsFilters(filters)}`);
  }

  function removeFilter(key: "state" | "attention" | "provider" | "createdFrom" | "createdTo") {
    const filters = { ...parsed.filters };
    delete filters[key];
    applyFilters(filters);
  }

  function nextPage() {
    if (!page?.next_cursor || query.isFetching) return;
    setPagination({ search, cursor: page.next_cursor ?? undefined, history: [...cursorHistory, cursor] });
  }

  function previousPage() {
    if (cursorHistory.length === 0 || query.isFetching) return;
    setPagination({ search, cursor: cursorHistory[cursorHistory.length - 1], history: cursorHistory.slice(0, -1) });
  }

  return (
    <section aria-labelledby="operations-heading">
      <header className="page-header">
        <div><p className="eyebrow">PROTECTED ACTIONS</p><h1 id="operations-heading" data-page-heading tabIndex={-1}>Operations</h1><p>Inspect protected agent actions, their current status, and durable technical evidence.</p></div>
        <OperationIdNavigation onNavigate={(operationId) => navigate(`/operations/${encodeURIComponent(operationId)}`)} />
      </header>
      <OperationFilters values={parsed.filters} invalidSearch={parsed.invalid} onApply={applyFilters} onRemove={removeFilter} onClear={() => navigate("/operations")} />
      {query.isPending ? <Skeleton variant="table" label="Loading operations" /> : error ? (
        <DefensiveState kind="error" title="Unable to load operations" onRetry={() => void query.refetch()}><p>{error}</p></DefensiveState>
      ) : !page || page.items.length === 0 ? (
        <DefensiveState kind="empty" title={search ? "No operations match these filters" : "No operations yet"}><p>{search ? "Try changing or clearing the current filters." : "Stateback is ready. Connect a provider and submit your first protected operation."}</p></DefensiveState>
      ) : <>{query.isFetching && <p role="status">Loading page…</p>}<OperationTable operations={page.items} onNavigate={(operationId) => navigate(`/operations/${encodeURIComponent(operationId)}`)} /><footer className="operation-pagination" aria-label="Operations pagination"><p>Showing up to {parsed.filters.limit} results</p><div><button type="button" className="primitive-button" disabled={cursorHistory.length === 0 || query.isFetching} onClick={previousPage}>Previous</button><button type="button" className="primitive-button" disabled={!page.next_cursor || query.isFetching} onClick={nextPage}>Next</button></div></footer></>}
    </section>
  );
}
