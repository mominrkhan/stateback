import { useCallback, useEffect, useRef, useState } from "react";

import type { OperatorClient } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { Operation } from "../../api/types";
import { DefensiveState } from "../../components/DefensiveState";
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

interface PageState {
  items: Operation[];
  nextCursor: string | null;
  loading: boolean;
  error: string | null;
}

const INITIAL_PAGE: PageState = { items: [], nextCursor: null, loading: true, error: null };
const DEFAULT_CREATE_ABORT_CONTROLLER = () => new AbortController();
const DEFAULT_RELEASE_ABORT_CONTROLLER = () => undefined;

export function OperationsPage({
  client,
  search,
  navigate,
  createAbortController = DEFAULT_CREATE_ABORT_CONTROLLER,
  releaseAbortController = DEFAULT_RELEASE_ABORT_CONTROLLER,
}: OperationsPageProps) {
  const parsed = parseOperationsSearch(search);
  const filtersRef = useRef(parsed.filters);
  const activeRequest = useRef<AbortController | null>(null);
  const requestGeneration = useRef(0);
  const [cursor, setCursor] = useState<string | undefined>();
  const [cursorHistory, setCursorHistory] = useState<Array<string | undefined>>([]);
  const [page, setPage] = useState<PageState>(INITIAL_PAGE);

  const load = useCallback(async (
    filters: OperationsFilterValues,
    targetCursor: string | undefined,
    commitCursor?: () => void,
  ) => {
    activeRequest.current?.abort();
    const controller = createAbortController();
    activeRequest.current = controller;
    const generation = ++requestGeneration.current;
    setPage((current) => ({ ...current, loading: true, error: null }));
    try {
      const result = await client.list(toApiFilters(filters, targetCursor), controller.signal);
      if (controller.signal.aborted || generation !== requestGeneration.current) return;
      commitCursor?.();
      setPage({ items: result.items, nextCursor: result.next_cursor, loading: false, error: null });
    } catch (cause) {
      if (controller.signal.aborted || generation !== requestGeneration.current) return;
      if (cause instanceof ApiError && cause.status === 401) return;
      setPage((current) => ({
        ...current,
        loading: false,
        error: cause instanceof Error ? cause.message : "Unable to load operations",
      }));
    } finally {
      releaseAbortController(controller);
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  }, [client, createAbortController, releaseAbortController]);

  useEffect(() => {
    filtersRef.current = parsed.filters;
    setCursor(undefined);
    setCursorHistory([]);
    void load(parsed.filters, undefined);
    return () => {
      activeRequest.current?.abort();
      requestGeneration.current += 1;
    };
  }, [load, search]);

  function applyFilters(filters: OperationsFilterValues) {
    navigate(`/operations${serializeOperationsFilters(filters)}`);
  }

  function nextPage() {
    if (!page.nextCursor || page.loading) return;
    const nextCursor = page.nextCursor;
    void load(filtersRef.current, nextCursor, () => {
      setCursorHistory((history) => [...history, cursor]);
      setCursor(nextCursor);
    });
  }

  function previousPage() {
    if (cursorHistory.length === 0 || page.loading) return;
    const previousCursor = cursorHistory[cursorHistory.length - 1];
    void load(filtersRef.current, previousCursor, () => {
      setCursorHistory((history) => history.slice(0, -1));
      setCursor(previousCursor);
    });
  }

  return (
    <section aria-labelledby="operations-heading">
      <header className="page-header">
        <div>
          <p className="eyebrow">PROTECTED ACTIONS</p>
          <h1 id="operations-heading" data-page-heading tabIndex={-1}>Operations</h1>
          <p>Inspect protected agent actions, their current status, and durable technical evidence.</p>
        </div>
        <OperationIdNavigation onNavigate={(operationId) => navigate(`/operations/${encodeURIComponent(operationId)}`)} />
      </header>
      <OperationFilters
        values={parsed.filters}
        invalidSearch={parsed.invalid}
        onApply={applyFilters}
        onClear={() => navigate("/operations")}
      />
      {page.loading && page.items.length === 0 ? (
        <DefensiveState kind="loading" title="Loading operations" />
      ) : page.error ? (
        <DefensiveState kind="error" title="Unable to load operations" onRetry={() => void load(filtersRef.current, cursor)}>
          <p>{page.error}</p>
        </DefensiveState>
      ) : page.items.length === 0 ? (
        <DefensiveState kind="empty" title={search ? "No operations match these filters" : "No operations yet"}>
          <p>{search ? "Try changing or clearing the current filters." : "Stateback is ready. Connect a provider and submit your first protected operation."}</p>
        </DefensiveState>
      ) : (
        <>
          {page.loading && <p role="status">Loading page…</p>}
          <OperationTable operations={page.items} onNavigate={(operationId) => navigate(`/operations/${encodeURIComponent(operationId)}`)} />
          <footer className="operation-pagination" aria-label="Operations pagination">
            <p>Showing up to {parsed.filters.limit} results</p>
            <div>
              <button type="button" className="primitive-button" disabled={cursorHistory.length === 0 || page.loading} onClick={previousPage}>Previous</button>
              <button type="button" className="primitive-button" disabled={!page.nextCursor || page.loading} onClick={nextPage}>Next</button>
            </div>
          </footer>
        </>
      )}
    </section>
  );
}
