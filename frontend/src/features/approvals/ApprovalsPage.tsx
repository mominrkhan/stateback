import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { OperatorClient } from "../../api/client";
import { ApiError } from "../../api/errors";
import { queryRead } from "../../api/queryRead";
import type { ActionKey, Operation } from "../../api/types";
import { OperatorQueryBoundary } from "../../app/OperatorQueryBoundary";
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

export function ApprovalsPage(props: ApprovalsPageProps) {
  return <OperatorQueryBoundary><ApprovalsContent {...props} /></OperatorQueryBoundary>;
}

function ApprovalsContent({ client, createAbortController = DEFAULT_CREATE_ABORT_CONTROLLER, releaseAbortController = DEFAULT_RELEASE_ABORT_CONTROLLER, commandController }: ApprovalsPageProps) {
  const controller = useMemo(() => commandController ?? new CommandController(client), [client, commandController]);
  const queryClient = useQueryClient();
  const [cursor, setCursor] = useState<string | undefined>();
  const [cursorHistory, setCursorHistory] = useState<Array<string | undefined>>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [dialogAction, setDialogAction] = useState<ApprovalAction | null>(null);
  const [showValidation, setShowValidation] = useState(false);
  const [commandState, setCommandState] = useState<Readonly<CommandState>>(controller.state);

  const queue = useQuery({
    queryKey: ["operator", "approvals", cursor ?? null],
    queryFn: ({ signal }) => queryRead(signal, createAbortController, releaseAbortController, (readSignal) => client.list({ state: "AWAITING_APPROVAL", limit: 50, ...(cursor ? { cursor } : {}) }, readSignal)),
  });
  const detail = useQuery({
    queryKey: ["operator", "operation", selectedId],
    enabled: selectedId !== null,
    queryFn: ({ signal }) => queryRead(signal, createAbortController, releaseAbortController, (readSignal) => client.reconstruct(selectedId!, readSignal)),
  });
  const operations = queue.data?.items ?? [];
  const reconstruction = detail.data ?? null;
  const queueError = queue.error instanceof ApiError && queue.error.status === 401 ? null : queue.error instanceof Error ? queue.error.message : queue.error ? "Unable to load approvals" : null;
  const detailError = detail.error instanceof ApiError && detail.error.status === 401 ? null : detail.error instanceof Error ? detail.error.message : detail.error ? "Unable to load approval reconstruction" : null;

  useEffect(() => controller.subscribe((state) => {
    setCommandState(state);
    if (state.reconstruction) queryClient.setQueryData(["operator", "operation", state.reconstruction.operation.operation_id], state.reconstruction);
  }), [controller, queryClient]);

  function select(operation: Operation) {
    setSelectedId(operation.operation_id);
    setReason("");
    setDialogAction(null);
  }

  async function refreshAuthoritativeReads() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["operator", "approvals"] }),
      queryClient.invalidateQueries({ queryKey: ["operator", "operations"] }),
      queryClient.invalidateQueries({ queryKey: ["operator", "overview"] }),
      queryClient.invalidateQueries({ queryKey: ["operator", "recovery"] }),
    ]);
  }

  async function confirm() {
    if (!reconstruction || !dialogAction) return;
    const approval = currentApproval(reconstruction);
    if (!approval) return;
    setShowValidation(true);
    try { await controller.confirm(reconstruction, dialogAction, reason, approval.approval_id); }
    catch { return; }
    const latest = controller.state;
    setCommandState(latest);
    setReason(latest.reason);
    if (latest.reconstruction) queryClient.setQueryData(["operator", "operation", latest.reconstruction.operation.operation_id], latest.reconstruction);
    setDialogAction(null);
    setShowValidation(false);
    await refreshAuthoritativeReads();
  }

  async function retrySame() {
    if (!selectedId) return;
    await controller.retrySame(selectedId);
    const latest = controller.state;
    setCommandState(latest);
    if (latest.reconstruction) queryClient.setQueryData(["operator", "operation", selectedId], latest.reconstruction);
    await refreshAuthoritativeReads();
  }

  function abandon() {
    if (!selectedId) return;
    controller.abandon(selectedId, true);
    setCommandState(controller.state);
  }

  function nextPage() {
    if (!queue.data?.next_cursor || queue.isFetching) return;
    setCursorHistory((history) => [...history, cursor]);
    setCursor(queue.data.next_cursor);
    setSelectedId(null);
  }

  function previousPage() {
    if (cursorHistory.length === 0 || queue.isFetching) return;
    setCursor(cursorHistory.at(-1));
    setCursorHistory((history) => history.slice(0, -1));
    setSelectedId(null);
  }

  return <div className="approvals-page">
    <header className="page-header"><p className="eyebrow">DECISION QUEUE</p><h1 id="approvals-page-heading" data-page-heading tabIndex={-1}>Approvals</h1><p>Review exactly what an agent is asking to do before authorizing it.</p></header>
    {queue.isPending ? <DefensiveState kind="loading" title="Loading approval queue" /> : queueError ? <DefensiveState kind="error" title="Unable to load approvals" onRetry={() => void queue.refetch()}><p>{queueError}</p></DefensiveState> : operations.length === 0 && !reconstruction ? <DefensiveState kind="empty" title="No approvals waiting"><p>There are no agent actions awaiting your approval.</p></DefensiveState> : <div className="approvals-layout"><div>{queue.isFetching && <p role="status">Loading approval page…</p>}{operations.length === 0 ? <DefensiveState kind="empty" title="No approvals waiting"><p>There are no agent actions awaiting your approval.</p></DefensiveState> : <><ApprovalQueue operations={operations} selectedOperationId={selectedId} disabled={detail.isFetching} onSelect={select} /><nav className="operation-pagination" aria-label="Approval queue pagination"><button type="button" className="primitive-button" disabled={cursorHistory.length === 0 || queue.isFetching} onClick={previousPage}>Previous</button><button type="button" className="primitive-button" disabled={!queue.data?.next_cursor || queue.isFetching} onClick={nextPage}>Next</button></nav></>}</div><aside aria-label="Selected approval">{detail.isFetching && !reconstruction ? <DefensiveState kind="loading" title="Loading approval details" /> : detailError ? <DefensiveState kind="error" title="Unable to load approval details" onRetry={() => void detail.refetch()}><p>{detailError}</p></DefensiveState> : reconstruction ? <ApprovalReview reconstruction={reconstruction} commandState={commandState} reason={reason} dialogAction={dialogAction} showValidation={showValidation} onReasonChange={setReason} onOpenDialog={(action) => { setDialogAction(action); setShowValidation(false); }} onCloseDialog={() => setDialogAction(null)} onConfirm={() => void confirm()} onRetrySame={() => void retrySame()} onAbandon={abandon} /> : <p>Select an operation to review its current approval.</p>}</aside></div>}
  </div>;
}
