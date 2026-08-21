import { useEffect, useState } from "react";

import type { ActionKey, Approval, Reconstruction } from "../../api/types";
import { CommandOutcome, type CommandOutcomeKind } from "../../components/CommandOutcome";
import { ConfirmationDialog } from "../../components/ConfirmationDialog";
import { CopyableId } from "../../components/CopyableId";
import { OperatorReasonField, validateOperatorReason } from "../../components/OperatorReasonField";
import { StateBadge } from "../../components/StateBadge";
import { SummaryPanel } from "../detail/SummaryPanel";
import type { CommandState } from "../commands/commandController";

type ApprovalAction = Extract<ActionKey, "approve" | "reject">;

const LABELS: Record<ApprovalAction, string> = {
  approve: "Approve operation",
  reject: "Reject operation",
};

function consequence(action: ApprovalAction): string {
  return action === "approve"
    ? "This records an approval decision. It does not mean the external effect is complete."
    : "This records a rejection decision. It makes no claim about an external provider outcome.";
}

function outcomeKind(phase: CommandState["phase"]): CommandOutcomeKind | null {
  if (phase === "idle") return null;
  if (phase === "submitting") return "submitting";
  if (phase === "accepted-reloading") return "accepted-reloading";
  if (phase === "accepted") return "accepted";
  if (phase === "conflict") return "conflict";
  if (phase === "forbidden") return "forbidden";
  if (phase === "validation-error") return "validation-error";
  if (phase === "rate-limited") return "rate-limited";
  if (phase === "indeterminate") return "transport-error";
  if (phase === "authoritative-reloaded") return "authoritative-reloaded";
  return "error";
}

interface ApprovalReviewProps {
  reconstruction: Reconstruction;
  commandState: Readonly<CommandState>;
  reason: string;
  dialogAction: ApprovalAction | null;
  showValidation: boolean;
  onReasonChange: (reason: string) => void;
  onOpenDialog: (action: ApprovalAction) => void;
  onCloseDialog: () => void;
  onConfirm: () => void;
  onRetrySame: () => void;
  onAbandon: () => void;
}

export function currentApproval(reconstruction: Reconstruction): Approval | null {
  const id = reconstruction.operation.current_approval_id;
  return id === null ? null : reconstruction.approvals.find((approval) => approval.approval_id === id) ?? null;
}

export function ApprovalReview({
  reconstruction,
  commandState,
  reason,
  dialogAction,
  showValidation,
  onReasonChange,
  onOpenDialog,
  onCloseDialog,
  onConfirm,
  onRetrySame,
  onAbandon,
}: ApprovalReviewProps) {
  const { operation } = reconstruction;
  const approval = currentApproval(reconstruction);
  const commandForSelection = commandState.operationId === operation.operation_id;
  const controlsDisabled = commandForSelection && commandState.controlsDisabled;
  const allowed = [...new Set(reconstruction.available_actions)].filter(
    (action): action is ApprovalAction => action === "approve" || action === "reject",
  );
  const validation = dialogAction ? validateOperatorReason(dialogAction, reason) : null;
  const kind = commandForSelection ? outcomeKind(commandState.phase) : null;
  const [reviewingAbandonment, setReviewingAbandonment] = useState(false);

  useEffect(() => setReviewingAbandonment(false), [operation.operation_id, commandState.phase]);

  return (
    <section aria-labelledby="approval-review-heading">
      <header>
        <h2 id="approval-review-heading">Approval review</h2>
        <StateBadge state={operation.state} />
      </header>
      <dl>
        <div><dt>Operation ID</dt><dd><CopyableId value={operation.operation_id} label="operation ID" /></dd></div>
        <div><dt>Expected version</dt><dd>{operation.version}</dd></div>
        <div><dt>Current approval ID</dt><dd>{approval ? <CopyableId value={approval.approval_id} label="approval ID" /> : "Not present"}</dd></div>
        <div><dt>Intent digest</dt><dd><CopyableId value={operation.intent.intent_digest} label="intent digest" /></dd></div>
        <div><dt>Effect</dt><dd>{operation.intent.effect.provider} / {operation.intent.effect.action} / {operation.intent.effect.version}</dd></div>
      </dl>
      <SummaryPanel reconstruction={reconstruction} />
      <OperatorReasonField
        actionKey={dialogAction ?? allowed[0] ?? "approve"}
        value={reason}
        disabled={controlsDisabled}
        showValidation={showValidation}
        onChange={onReasonChange}
      />
      <div className="approval-actions" aria-label="Available approval actions">
        {approval && allowed.map((action) => (
          <button
            key={action}
            type="button"
            className={`primitive-button ${action === "reject" ? "primitive-button--danger" : "primitive-button--primary"}`}
            disabled={controlsDisabled}
            onClick={() => onOpenDialog(action)}
          >
            {LABELS[action]}
          </button>
        ))}
      </div>
      {!approval && allowed.length > 0 && (
        <p role="alert">Approval controls are unavailable because the current approval binding is absent.</p>
      )}
      {kind && (
        <CommandOutcome kind={kind} title={commandState.phase === "conflict" ? "Approval changed on the server" : "Approval command status"}>
          <p>{commandState.message ?? "The command is being processed."}</p>
          {commandState.phase === "conflict" && <p>Your reason is preserved. Review the authoritative version before confirming a new request.</p>}
          {commandState.retrySameRequest && (
            <button type="button" className="primitive-button" onClick={onRetrySame}>Retry same request</button>
          )}
          {commandState.phase === "indeterminate" && (
            reviewingAbandonment ? (
              <div role="alert">
                <p>Abandoning this local retry record does not prove the server rejected or skipped the command.</p>
                <button type="button" className="primitive-button primitive-button--danger" onClick={onAbandon}>Confirm abandon local retry</button>
                <button type="button" className="primitive-button" onClick={() => setReviewingAbandonment(false)}>Keep local retry</button>
              </div>
            ) : (
              <button type="button" className="primitive-button" onClick={() => setReviewingAbandonment(true)}>Review abandonment</button>
            )
          )}
        </CommandOutcome>
      )}
      <ConfirmationDialog
        open={dialogAction !== null}
        title={dialogAction === "reject" ? "Confirm rejection" : "Confirm approval"}
        description={dialogAction ? consequence(dialogAction) : "Review the exact immutable binding."}
        confirmLabel={dialogAction === "reject" ? "Confirm rejection" : "Confirm approval"}
        pending={commandForSelection && (commandState.phase === "submitting" || commandState.phase === "accepted-reloading")}
        confirmDisabled={!validation || validation.error !== null || !approval}
        onCancel={onCloseDialog}
        onConfirm={onConfirm}
      >
        <dl>
          <div><dt>Operation ID</dt><dd>{operation.operation_id}</dd></div>
          <div><dt>Expected version</dt><dd>{operation.version}</dd></div>
          <div><dt>Approval ID</dt><dd>{approval?.approval_id ?? "Not present"}</dd></div>
          <div><dt>Intent digest</dt><dd>{operation.intent.intent_digest}</dd></div>
          <div><dt>Effect</dt><dd>{operation.intent.effect.provider} / {operation.intent.effect.action} / {operation.intent.effect.version}</dd></div>
          <div><dt>Action</dt><dd>{dialogAction ?? "Not selected"}</dd></div>
          <div><dt>Exact submitted reason</dt><dd>{validation?.normalized ?? ""}</dd></div>
          <div><dt>Consequence</dt><dd>{dialogAction ? consequence(dialogAction) : ""}</dd></div>
        </dl>
      </ConfirmationDialog>
    </section>
  );
}
