import { useEffect, useMemo, useRef, useState } from "react";

import type { OperatorClient } from "../../api/client";
import type { ActionKey, Operation, Reconstruction } from "../../api/types";
import { ActionGate, ACTION_LABELS } from "../../components/ActionGate";
import { CommandOutcome } from "../../components/CommandOutcome";
import { ConfirmationDialog } from "../../components/ConfirmationDialog";
import { CopyableId } from "../../components/CopyableId";
import { DefensiveState } from "../../components/DefensiveState";
import { OperatorReasonField, validateOperatorReason } from "../../components/OperatorReasonField";
import { StateBadge } from "../../components/StateBadge";
import { Timestamp } from "../../components/Timestamp";
import { CommandAttemptRegistry, sessionCommandAttempts } from "../commands/attemptRegistry";
import { CommandController, type CommandState } from "../commands/commandController";

const RECOVERY_QUEUES = [
  { state: "MANUAL_INTERVENTION", title: "Manual intervention" },
  { state: "COMPENSATION_UNKNOWN", title: "Compensation outcome unknown" },
  { state: "COMPENSATION_FAILED", title: "Compensation failed" },
  { state: "COMPENSATING", title: "Active compensation monitoring" },
] as const;

const DEFAULT_CREATE_ABORT = () => new AbortController();
const DEFAULT_RELEASE_ABORT = () => undefined;

interface RecoveryData {
  queues: Record<string, Operation[]>;
  loading: boolean;
  error: string | null;
}

const INITIAL_DATA: RecoveryData = { queues: {}, loading: true, error: null };

export interface RecoveryPageProps {
  client: OperatorClient;
  attemptRegistry?: CommandAttemptRegistry;
  createAbortController?: () => AbortController;
  releaseAbortController?: (controller: AbortController) => void;
  sessionGeneration?: number;
  isCurrentGeneration?: (generation: number) => boolean;
}

function warningFor(action: ActionKey): string {
  if (action === "verify") return "Verification may still be unable to establish the provider outcome. Do not retry the external effect blindly.";
  if (action === "compensate" || action === "retry_compensation") {
    return "Compensation is another side effect. It may fail or become COMPENSATION_UNKNOWN, and it does not erase the original history.";
  }
  if (action === "escalate_compensation") return "Escalation records the compensation problem for operator handling. It does not prove rollback or external recovery.";
  return "This consequential command is revalidated by the server.";
}

function outcomeKind(state: CommandState): Parameters<typeof CommandOutcome>[0]["kind"] {
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

export function RecoveryPage({
  client,
  attemptRegistry = sessionCommandAttempts,
  createAbortController = DEFAULT_CREATE_ABORT,
  releaseAbortController = DEFAULT_RELEASE_ABORT,
  sessionGeneration = 0,
  isCurrentGeneration = () => true,
}: RecoveryPageProps) {
  const commandController = useMemo(() => new CommandController(client, { registry: attemptRegistry }), [client, attemptRegistry]);
  const activeQueueRead = useRef<AbortController | null>(null);
  const activeDetailRead = useRef<AbortController | null>(null);
  const queueGeneration = useRef(0);
  const detailGeneration = useRef(0);
  const [data, setData] = useState<RecoveryData>(INITIAL_DATA);
  const [detail, setDetail] = useState<Reconstruction | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [selectedAction, setSelectedAction] = useState<ActionKey | null>(null);
  const [reason, setReason] = useState("");
  const [showValidation, setShowValidation] = useState(false);
  const [commandState, setCommandState] = useState<Readonly<CommandState>>(commandController.state);
  const [abandonAcknowledged, setAbandonAcknowledged] = useState(false);

  async function loadQueues() {
    activeQueueRead.current?.abort();
    const controller = createAbortController();
    activeQueueRead.current = controller;
    const generation = ++queueGeneration.current;
    const startingSession = sessionGeneration;
    setData((current) => ({ ...current, loading: true, error: null }));
    try {
      const pages = await Promise.all(RECOVERY_QUEUES.map((queue) => client.list({ state: queue.state, limit: 50 }, controller.signal)));
      if (controller.signal.aborted || generation !== queueGeneration.current || !isCurrentGeneration(startingSession)) return;
      setData({
        queues: Object.fromEntries(RECOVERY_QUEUES.map((queue, index) => [queue.state, pages[index].items])),
        loading: false,
        error: null,
      });
    } catch (cause) {
      if (controller.signal.aborted || generation !== queueGeneration.current || !isCurrentGeneration(startingSession)) return;
      setData((current) => ({ ...current, loading: false, error: cause instanceof Error ? cause.message : "Unable to load recovery queues" }));
    } finally {
      releaseAbortController(controller);
      if (activeQueueRead.current === controller) activeQueueRead.current = null;
    }
  }

  useEffect(() => {
    void loadQueues();
    return () => {
      activeQueueRead.current?.abort();
      activeDetailRead.current?.abort();
      queueGeneration.current += 1;
      detailGeneration.current += 1;
    };
  }, [client, sessionGeneration]);

  useEffect(() => commandController.subscribe((state) => {
    setCommandState(state);
    if (state.reconstruction) setDetail(state.reconstruction);
    if (state.phase === "accepted" || state.phase === "authoritative-reloaded") void loadQueues();
  }), [commandController]);

  async function selectOperation(operationId: string) {
    activeDetailRead.current?.abort();
    const controller = createAbortController();
    activeDetailRead.current = controller;
    const generation = ++detailGeneration.current;
    const startingSession = sessionGeneration;
    setSelectedAction(null);
    setReason("");
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const reconstruction = await client.reconstruct(operationId, controller.signal);
      if (controller.signal.aborted || generation !== detailGeneration.current || !isCurrentGeneration(startingSession)) return;
      setDetail(reconstruction);
    } catch (cause) {
      if (controller.signal.aborted || generation !== detailGeneration.current || !isCurrentGeneration(startingSession)) return;
      setDetailError(cause instanceof Error ? cause.message : "Unable to load authoritative reconstruction");
    } finally {
      if (generation === detailGeneration.current) setDetailLoading(false);
      releaseAbortController(controller);
      if (activeDetailRead.current === controller) activeDetailRead.current = null;
    }
  }

  async function confirmCommand() {
    if (!detail || !selectedAction) return;
    const validation = validateOperatorReason(selectedAction, reason);
    if (validation.error) { setShowValidation(true); return; }
    setShowValidation(false);
    await commandController.confirm(detail, selectedAction, validation.normalized);
    setSelectedAction(null);
  }

  const outcomeVisible = commandState.phase !== "idle";
  const retained = detail ? commandController.retained(detail.operation.operation_id) : undefined;
  const commandPending = commandState.phase === "submitting" || commandState.phase === "accepted-reloading";

  return (
    <section aria-labelledby="recovery-heading">
      <header className="page-header">
        <p className="eyebrow">AUTHORITATIVE RECOVERY</p>
        <h1 id="recovery-heading" data-page-heading tabIndex={-1}>Recovery</h1>
        <p>Recovery controls appear only after loading authoritative reconstruction and exact backend eligibility.</p>
      </header>
      <aside aria-label="Recovery safety notice">
        <strong>Unknown is not failure.</strong> An operation in UNKNOWN is not included as actionable here. Compensation is not universal rollback.
      </aside>
      {data.loading && Object.keys(data.queues).length === 0 ? (
        <DefensiveState kind="loading" title="Loading recovery queues" />
      ) : data.error ? (
        <DefensiveState kind="error" title="Unable to load recovery queues" onRetry={() => void loadQueues()}><p>{data.error}</p></DefensiveState>
      ) : (
        <div className="recovery-queues">
          {RECOVERY_QUEUES.map((queue) => {
            const operations = data.queues[queue.state] ?? [];
            return (
              <section key={queue.state} aria-labelledby={`queue-${queue.state}`}>
                <h2 id={`queue-${queue.state}`}>{queue.title}</h2>
                <p>Exact state: <code>{queue.state}</code></p>
                {operations.length === 0 ? <p>No operations in this queue.</p> : (
                  <ul>
                    {operations.map((operation) => (
                      <li key={operation.operation_id}>
                        <button type="button" className="primitive-button" onClick={() => void selectOperation(operation.operation_id)}>
                          {operation.intent.effect.provider} / {operation.intent.effect.action} — {operation.operation_id}
                        </button>
                        <StateBadge state={operation.state} />
                        <Timestamp value={operation.updated_at} />
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            );
          })}
        </div>
      )}

      <section aria-labelledby="recovery-controls-heading">
        <h2 id="recovery-controls-heading">Selected recovery operation</h2>
        {detailLoading ? <DefensiveState kind="loading" title="Loading authoritative reconstruction" /> : detailError ? (
          <DefensiveState kind="error" title="Unable to load recovery controls"><p>{detailError}</p></DefensiveState>
        ) : !detail ? <p>Select a queued operation to inspect backend-authorized controls.</p> : (
          <>
            <CopyableId value={detail.operation.operation_id} label="operation ID" />
            <StateBadge state={detail.operation.state} />
            <p>Version {detail.operation.version}; {detail.operation.intent.effect.provider} / {detail.operation.intent.effect.action} / {detail.operation.intent.effect.version}</p>
            <ActionGate
              availableActions={detail.available_actions}
              disabled={commandState.controlsDisabled || retained !== undefined}
              onAction={(action) => { setReason(""); setShowValidation(false); setSelectedAction(action); }}
            />
          </>
        )}
      </section>

      {outcomeVisible && commandState.message && (
        <CommandOutcome kind={outcomeKind(commandState)} title="Recovery command status">
          <p>{commandState.message}</p>
          {commandState.retrySameRequest && detail && (
            <button type="button" className="primitive-button" onClick={() => void commandController.retrySame(detail.operation.operation_id)}>Retry same request</button>
          )}
          {retained && detail && (
            <div>
              <p>Abandoning this local retry record does not prove the server did nothing.</p>
              <label><input type="checkbox" checked={abandonAcknowledged} onChange={(event) => setAbandonAcknowledged(event.currentTarget.checked)} /> I understand the command outcome may remain ambiguous.</label>
              <button type="button" className="primitive-button" disabled={!abandonAcknowledged} onClick={() => { commandController.abandon(detail.operation.operation_id, true); setAbandonAcknowledged(false); }}>Abandon local retry</button>
            </div>
          )}
        </CommandOutcome>
      )}

      <ConfirmationDialog
        open={selectedAction !== null && detail !== null}
        title={selectedAction ? ACTION_LABELS[selectedAction] : "Review recovery command"}
        description={selectedAction ? warningFor(selectedAction) : "Review the exact authoritative binding."}
        confirmLabel={selectedAction ? ACTION_LABELS[selectedAction] : "Confirm"}
        pending={commandPending}
        confirmDisabled={selectedAction ? validateOperatorReason(selectedAction, reason).error !== null : true}
        onCancel={() => setSelectedAction(null)}
        onConfirm={() => void confirmCommand()}
      >
        {detail && selectedAction && (
          <>
            <dl>
              <div><dt>Operation ID</dt><dd>{detail.operation.operation_id}</dd></div>
              <div><dt>Expected version</dt><dd>{detail.operation.version}</dd></div>
              <div><dt>Action</dt><dd><code>{selectedAction}</code></dd></div>
              <div><dt>Effect</dt><dd>{detail.operation.intent.effect.provider} / {detail.operation.intent.effect.action} / {detail.operation.intent.effect.version}</dd></div>
              <div><dt>Intent digest</dt><dd>{detail.operation.intent.intent_digest}</dd></div>
              {detail.compensation && <div><dt>Compensation context</dt><dd>{detail.compensation.compensation_id} / {detail.compensation.kind}</dd></div>}
            </dl>
            <p>{warningFor(selectedAction)}</p>
            <OperatorReasonField actionKey={selectedAction} value={reason} onChange={setReason} disabled={commandPending} showValidation={showValidation} />
          </>
        )}
      </ConfirmationDialog>
    </section>
  );
}
