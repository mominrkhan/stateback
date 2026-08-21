import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { OperatorClient } from "../../api/client";
import { ApiError } from "../../api/errors";
import type { ActionKey, Operation, Reconstruction } from "../../api/types";
import { DefensiveState } from "../../components/DefensiveState";
import { CommandController, type CommandState } from "../commands/commandController";
import { ApprovalQueue } from "./ApprovalQueue";
import { ApprovalReview, currentApproval } from "./ApprovalReview";

type ApprovalAction = Extract<ActionKey, "approve" | "reject">;

const DEFAULT_CREATE_ABORT_CONTROLLER = () => new AbortController();
const DEFAULT_RELEASE_ABORT_CONTROLLER = () => undefined;

export interface ApprovalsPageProps {
  client: OperatorClient;
  createAbortController?: () => AbortController;
  releaseAbortController?: (controller: AbortController) => void;
  commandController?: CommandController;
}

export function ApprovalsPage({
  client,
  createAbortController = DEFAULT_CREATE_ABORT_CONTROLLER,
  releaseAbortController = DEFAULT_RELEASE_ABORT_CONTROLLER,
  commandController,
}: ApprovalsPageProps) {
  const controller = useMemo(() => commandController ?? new CommandController(client), [client, commandController]);
  const queueRequest = useRef<AbortController | null>(null);
  const detailRequest = useRef<AbortController | null>(null);
  const queueGeneration = useRef(0);
  const detailGeneration = useRef(0);
  const [operations, setOperations] = useState<Operation[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string | undefined>();
  const [cursorHistory, setCursorHistory] = useState<Array<string | undefined>>([]);
  const [queueLoading, setQueueLoading] = useState(true);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Reconstruction | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [dialogAction, setDialogAction] = useState<ApprovalAction | null>(null);
  const [showValidation, setShowValidation] = useState(false);
  const [commandState, setCommandState] = useState<Readonly<CommandState>>(controller.state);

  useEffect(() => controller.subscribe(setCommandState), [controller]);

  const loadQueue = useCallback(async (targetCursor?: string, commitCursor?: () => void) => {
    queueRequest.current?.abort();
    const request = createAbortController();
    queueRequest.current = request;
    const generation = ++queueGeneration.current;
    setQueueLoading(true);
    setQueueError(null);
    try {
      const result = await client.list({ state: "AWAITING_APPROVAL", limit: 50, ...(targetCursor ? { cursor: targetCursor } : {}) }, request.signal);
      if (request.signal.aborted || generation !== queueGeneration.current) return;
      commitCursor?.();
      setOperations(result.items);
      setNextCursor(result.next_cursor);
      setQueueLoading(false);
    } catch (cause) {
      if (request.signal.aborted || generation !== queueGeneration.current) return;
      if (cause instanceof ApiError && cause.status === 401) return;
      setQueueLoading(false);
      setQueueError(cause instanceof Error ? cause.message : "Unable to load approvals");
    } finally {
      releaseAbortController(request);
      if (queueRequest.current === request) queueRequest.current = null;
    }
  }, [client, createAbortController, releaseAbortController]);

  useEffect(() => {
    void loadQueue();
    return () => {
      queueRequest.current?.abort();
      detailRequest.current?.abort();
      queueGeneration.current += 1;
      detailGeneration.current += 1;
    };
  }, [loadQueue]);

  async function select(operation: Operation) {
    detailRequest.current?.abort();
    const request = createAbortController();
    detailRequest.current = request;
    const generation = ++detailGeneration.current;
    setSelectedId(operation.operation_id);
    setDetail(null);
    setDetailLoading(true);
    setDetailError(null);
    setReason("");
    setDialogAction(null);
    try {
      const reconstruction = await client.reconstruct(operation.operation_id, request.signal);
      if (request.signal.aborted || generation !== detailGeneration.current) return;
      setDetail(reconstruction);
      setDetailLoading(false);
    } catch (cause) {
      if (request.signal.aborted || generation !== detailGeneration.current) return;
      if (cause instanceof ApiError && cause.status === 401) return;
      setDetailLoading(false);
      setDetailError(cause instanceof Error ? cause.message : "Unable to load approval reconstruction");
    } finally {
      releaseAbortController(request);
      if (detailRequest.current === request) detailRequest.current = null;
    }
  }

  async function confirm() {
    if (!detail || !dialogAction) return;
    const approval = currentApproval(detail);
    if (!approval) return;
    setShowValidation(true);
    try {
      await controller.confirm(detail, dialogAction, reason, approval.approval_id);
    } catch {
      return;
    }
    const latest = controller.state;
    setCommandState(latest);
    setReason(latest.reason);
    if (latest.reconstruction) setDetail(latest.reconstruction);
    setDialogAction(null);
    setShowValidation(false);
    await loadQueue(cursor);
  }

  async function retrySame() {
    if (!selectedId) return;
    await controller.retrySame(selectedId);
    const latest = controller.state;
    setCommandState(latest);
    if (latest.reconstruction) setDetail(latest.reconstruction);
    await loadQueue(cursor);
  }

  function abandon() {
    if (!selectedId) return;
    controller.abandon(selectedId, true);
    setCommandState(controller.state);
  }

  function nextPage() {
    if (!nextCursor || queueLoading) return;
    const target = nextCursor;
    void loadQueue(target, () => {
      setCursorHistory((history) => [...history, cursor]);
      setCursor(target);
      setSelectedId(null);
      setDetail(null);
    });
  }

  function previousPage() {
    if (cursorHistory.length === 0 || queueLoading) return;
    const target = cursorHistory.at(-1);
    void loadQueue(target, () => {
      setCursorHistory((history) => history.slice(0, -1));
      setCursor(target);
      setSelectedId(null);
      setDetail(null);
    });
  }

  return (
    <div className="approvals-page">
      <header className="page-header">
        <p className="eyebrow">DELIBERATE DECISIONS</p>
        <h1 id="approvals-page-heading" data-page-heading tabIndex={-1}>Approvals</h1>
        <p>Select one operation to load its authoritative approval binding.</p>
      </header>
      {queueLoading && operations.length === 0 ? (
        <DefensiveState kind="loading" title="Loading approval queue" />
      ) : queueError ? (
        <DefensiveState kind="error" title="Unable to load approvals" onRetry={() => void loadQueue(cursor)}><p>{queueError}</p></DefensiveState>
      ) : operations.length === 0 && !detail ? (
        <DefensiveState kind="empty" title="No approvals awaiting a decision" />
      ) : (
        <div className="approvals-layout">
          <div>
            {queueLoading && <p role="status">Loading approval page…</p>}
            {operations.length === 0 ? <DefensiveState kind="empty" title="No approvals awaiting a decision" /> : (
              <>
                <ApprovalQueue operations={operations} selectedOperationId={selectedId} disabled={detailLoading} onSelect={(operation) => void select(operation)} />
                <nav className="operation-pagination" aria-label="Approval queue pagination">
                  <button type="button" className="primitive-button" disabled={cursorHistory.length === 0 || queueLoading} onClick={previousPage}>Previous</button>
                  <button type="button" className="primitive-button" disabled={!nextCursor || queueLoading} onClick={nextPage}>Next</button>
                </nav>
              </>
            )}
          </div>
          <aside aria-label="Selected approval">
            {detailLoading ? <DefensiveState kind="loading" title="Loading approval details" />
              : detailError ? <DefensiveState kind="error" title="Unable to load approval details"><p>{detailError}</p></DefensiveState>
                : detail ? (
                  <ApprovalReview
                    reconstruction={detail}
                    commandState={commandState}
                    reason={reason}
                    dialogAction={dialogAction}
                    showValidation={showValidation}
                    onReasonChange={setReason}
                    onOpenDialog={(action) => { setDialogAction(action); setShowValidation(false); }}
                    onCloseDialog={() => setDialogAction(null)}
                    onConfirm={() => void confirm()}
                    onRetrySame={() => void retrySame()}
                    onAbandon={abandon}
                  />
                ) : <p>Select an operation to review its current approval.</p>}
          </aside>
        </div>
      )}
    </div>
  );
}
