import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { OperatorClient } from "../api/client";
import { queryRead } from "../api/queryRead";
import type { ActionKey, Reconstruction } from "../api/types";
import { ActionGate, ACTION_LABELS } from "../components/ActionGate";
import { CommandOutcome, type CommandOutcomeKind } from "../components/CommandOutcome";
import { ConfirmationDialog } from "../components/ConfirmationDialog";
import { DefensiveState } from "../components/DefensiveState";
import { Skeleton } from "../components/Skeleton";
import { OperatorReasonField, validateOperatorReason } from "../components/OperatorReasonField";
import { CommandController, type CommandState } from "../features/commands/commandController";
import { sessionCommandAttempts } from "../features/commands/attemptRegistry";
import { OperationDetailPage } from "../features/detail/OperationDetailPage";
import { AdvisorySummary } from "../features/semantic/AdvisorySummary";
import type { AuthSessionValue } from "../auth/AuthSession";

interface OperationDetailRouteProps {
  client: OperatorClient;
  operationId: string;
  session: AuthSessionValue;
  navigate: (href: string) => void;
}

function outcomeKind(state: CommandState): CommandOutcomeKind {
  if (state.phase === "accepted") return "accepted";
  if (state.phase === "authoritative-reloaded") return "authoritative-reloaded";
  if (state.phase === "accepted-reloading") return "accepted-reloading";
  if (state.phase === "submitting") return "submitting";
  if (state.phase === "conflict") return "conflict";
  if (state.phase === "forbidden") return "forbidden";
  if (state.phase === "validation-error") return "validation-error";
  if (state.phase === "rate-limited") return "rate-limited";
  if (state.phase === "indeterminate") return "transport-error";
  return "error";
}

function consequence(action: ActionKey): string {
  if (action === "approve") return "Approval authorizes the bound intent to enter the ordinary runtime path; it does not prove provider execution.";
  if (action === "reject") return "Rejection denies this bound approval request and does not call the provider.";
  if (action === "verify") return "Verification gathers evidence and may remain inconclusive. It does not authorize blind retry.";
  if (action === "escalate_compensation") return "Escalation records an unresolved compensation condition; it does not prove recovery.";
  return "Compensation is another side effect. It may fail or become unknown and never erases original history.";
}

export function OperationDetailRoute({ client, operationId, session, navigate }: OperationDetailRouteProps) {
  const controller = useMemo(
    () => new CommandController(client, { registry: sessionCommandAttempts }),
    [client],
  );
  const queryClient = useQueryClient();
  const detailKey = ["operator", "operation", operationId] as const;
  const detailQuery = useQuery({
    queryKey: detailKey,
    queryFn: ({ signal }) => queryRead(signal, session.createAbortController, session.releaseAbortController, (readSignal) => client.reconstruct(operationId, readSignal)),
  });
  const detail = detailQuery.data ?? null;
  const [commandError, setCommandError] = useState<string | null>(null);
  const [action, setAction] = useState<ActionKey | null>(null);
  const [reason, setReason] = useState("");
  const [showValidation, setShowValidation] = useState(false);
  const [commandState, setCommandState] = useState<Readonly<CommandState>>(controller.state);
  const [abandonAcknowledged, setAbandonAcknowledged] = useState(false);

  useEffect(() => {
    setAction(null);
    setReason("");
    setCommandError(null);
  }, [operationId, session.sessionGeneration]);

  useEffect(() => controller.subscribe((state) => {
    setCommandState(state);
    if (state.reconstruction) queryClient.setQueryData(detailKey, state.reconstruction);
    if (state.phase === "accepted" || state.phase === "authoritative-reloaded" || state.phase === "conflict") {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["operator", "operations"] }),
        queryClient.invalidateQueries({ queryKey: ["operator", "approvals"] }),
        queryClient.invalidateQueries({ queryKey: ["operator", "recovery"] }),
        queryClient.invalidateQueries({ queryKey: ["operator", "overview"] }),
      ]);
    }
  }), [controller, operationId, queryClient]);

  async function confirm() {
    if (!detail || !action) return;
    const validation = validateOperatorReason(action, reason);
    if (validation.error) {
      setShowValidation(true);
      return;
    }
    const approvalId = action === "approve" || action === "reject"
      ? detail.operation.current_approval_id ?? undefined
      : undefined;
    try {
      await controller.confirm(detail, action, validation.normalized, approvalId);
      setAction(null);
      setShowValidation(false);
    } catch (cause) {
      setShowValidation(true);
      setCommandError(cause instanceof Error ? cause.message : "Unable to submit command");
    }
  }

  const readError = detailQuery.error instanceof Error ? detailQuery.error.message : detailQuery.error ? "Unable to load operation reconstruction" : null;
  if (detailQuery.isPending && !detail) return <section aria-labelledby="detail-loading-heading"><h1 id="detail-loading-heading" data-page-heading tabIndex={-1}>Operation detail</h1><Skeleton variant="detail" label="Loading operation reconstruction" /></section>;
  if (readError && !detail) return <section aria-labelledby="detail-error-heading"><h1 id="detail-error-heading" data-page-heading tabIndex={-1}>Operation detail</h1><DefensiveState kind="error" title="Unable to load operation" onRetry={() => void detailQuery.refetch()}><p>{readError}</p></DefensiveState></section>;
  if (!detail) return <section aria-labelledby="detail-unsupported-heading"><h1 id="detail-unsupported-heading" data-page-heading tabIndex={-1}>Operation detail</h1><DefensiveState kind="unsupported" title="Unsupported operation response" /></section>;

  const retained = controller.retained(detail.operation.operation_id);
  const pending = commandState.phase === "submitting" || commandState.phase === "accepted-reloading";
  const currentApproval = detail.approvals.find(
    (approval) => approval.approval_id === detail.operation.current_approval_id,
  );
  const actions = (
    <>
      <ActionGate
        availableActions={detail.available_actions}
        disabled={commandState.controlsDisabled || retained !== undefined}
        onAction={(nextAction) => {
          setAction(nextAction);
          setReason("");
          setShowValidation(false);
        }}
      />
      {commandState.phase !== "idle" && commandState.message && (
        <CommandOutcome kind={outcomeKind(commandState)} title="Operator command status">
          <p>{commandState.message}</p>
          {commandState.retrySameRequest && (
            <button className="primitive-button" type="button" onClick={() => void controller.retrySame(detail.operation.operation_id)}>Retry same request</button>
          )}
          {retained && (
            <div>
              <p>Abandoning this browser retry record does not prove the server did nothing.</p>
              <label>
                <input type="checkbox" checked={abandonAcknowledged} onChange={(event) => setAbandonAcknowledged(event.currentTarget.checked)} />
                I understand the command outcome may remain ambiguous.
              </label>
              <button
                className="primitive-button"
                type="button"
                disabled={!abandonAcknowledged}
                onClick={() => {
                  controller.abandon(detail.operation.operation_id, true);
                  setCommandState(controller.state);
                  setAbandonAcknowledged(false);
                }}
              >Abandon local retry</button>
            </div>
          )}
        </CommandOutcome>
      )}
    </>
  );

  return (
    <>
      {commandError && <p role="alert">{commandError}</p>}
      <OperationDetailPage
        reconstruction={detail}
        actions={actions}
        advisory={<AdvisorySummary client={client} operation={detail.operation} />}
        onNavigate={navigate}
      />
      <ConfirmationDialog
        open={action !== null}
        title={action ? ACTION_LABELS[action] : "Review operator command"}
        description={action ? consequence(action) : "Review the authoritative binding."}
        confirmLabel={action ? ACTION_LABELS[action] : "Confirm"}
        pending={pending}
        confirmDisabled={!action || validateOperatorReason(action, reason).error !== null}
        onCancel={() => setAction(null)}
        onConfirm={() => void confirm()}
      >
        {action && (
          <>
            <dl>
              <div><dt>Operation ID</dt><dd>{detail.operation.operation_id}</dd></div>
              <div><dt>Expected version</dt><dd>{detail.operation.version}</dd></div>
              <div><dt>Action</dt><dd><code>{action}</code></dd></div>
              {(action === "approve" || action === "reject") && <div><dt>Approval ID</dt><dd>{currentApproval?.approval_id ?? "Unavailable"}</dd></div>}
              <div><dt>Intent digest</dt><dd>{detail.operation.intent.intent_digest}</dd></div>
              <div><dt>Effect</dt><dd>{detail.operation.intent.effect.provider} / {detail.operation.intent.effect.action} / {detail.operation.intent.effect.version}</dd></div>
              {detail.compensation && <div><dt>Compensation</dt><dd>{detail.compensation.compensation_id} / {detail.compensation.kind}</dd></div>}
            </dl>
            <p>{consequence(action)}</p>
            <OperatorReasonField actionKey={action} value={reason} onChange={setReason} disabled={pending} showValidation={showValidation} />
          </>
        )}
      </ConfirmationDialog>
    </>
  );
}
