import type { Reconstruction } from "../../api/types";
import { Timestamp } from "../../components/Timestamp";

function resolvedBy(reconstruction: Reconstruction, action: string): boolean {
  return reconstruction.reconciliations.some((item) => item.decision.action === action);
}

export function outcomeSummary(reconstruction: Reconstruction): string {
  const state = reconstruction.operation.state;
  if (state === "UNKNOWN") return "Stateback cannot yet prove whether the provider applied the action.";
  if (state === "VERIFYING") return "Stateback is checking the provider for evidence of what actually happened.";
  if (state === "COMPENSATING") return "The compensating action is in progress as a separate external effect.";
  if (state === "COMPENSATION_UNKNOWN") return "Stateback cannot yet prove whether the compensating action was applied.";
  if (state === "COMPENSATION_FAILED") return "The compensating action did not complete successfully.";
  if (state === "SUCCEEDED" && resolvedBy(reconstruction, "MARK_SUCCEEDED")) return "Provider evidence established that the action was applied; Stateback reconciled it to Succeeded without repeating it.";
  if (state === "FAILED" && resolvedBy(reconstruction, "MARK_FAILED")) return "Verification evidence established the operation's terminal failure state.";
  if (state === "SUCCEEDED") return "The durable operation record reports that the protected action succeeded.";
  if (state === "FAILED") return "The durable operation record reports that the protected action failed.";
  if (state === "AWAITING_APPROVAL") return "The action will not be authorized until an approver reviews its exact intent.";
  if (state === "MANUAL_INTERVENTION") return "Automatic recovery stopped and an operator must review the durable evidence.";
  return "The canonical Stateback lifecycle record is shown below.";
}

export function OutcomeExplanation({ reconstruction }: { reconstruction: Reconstruction }) {
  const state = reconstruction.operation.state;
  const latestVerification = reconstruction.verifications.at(-1);
  if (!["UNKNOWN", "VERIFYING", "COMPENSATION_UNKNOWN"].includes(state)) return null;

  return (
    <section className="outcome-explanation" aria-labelledby="outcome-explanation-heading">
      <p className="eyebrow">EXTERNAL TRUTH</p>
      <h2 id="outcome-explanation-heading">
        {state === "UNKNOWN" ? "Outcome unknown" : state === "VERIFYING" ? "Verifying external outcome" : "Compensation outcome unknown"}
      </h2>
      {state === "UNKNOWN" && <><p><strong>This does not mean the operation failed.</strong> The external action may already have happened even though Stateback does not have enough evidence to prove it.</p><p>Stateback will not blindly retry the action.</p></>}
      {state === "VERIFYING" && <p>Stateback is checking the provider for evidence of what actually happened. Verification may still remain inconclusive.</p>}
      {state === "COMPENSATION_UNKNOWN" && <p>The compensating action is itself an external side effect. Stateback cannot yet prove whether it was applied.</p>}
      <dl>
        <div><dt>Verification status</dt><dd>{latestVerification ? latestVerification.result ? `Completed: ${latestVerification.result.outcome}` : "Pending" : "No verification record"}</dd></div>
        <div><dt>Verification attempts</dt><dd>{reconstruction.verifications.length}</dd></div>
        <div><dt>Available evidence</dt><dd>{reconstruction.attempts.filter((attempt) => attempt.evidence !== null).length + reconstruction.verifications.filter((item) => item.result?.evidence).length} record(s)</dd></div>
        <div><dt>Next safe action</dt><dd>{reconstruction.available_actions.includes("verify") ? "Operator verification is available" : "No retry action is authorized by the backend"}</dd></div>
        {latestVerification?.result && <div><dt>Last verification</dt><dd><Timestamp value={latestVerification.result.completed_at} /></dd></div>}
      </dl>
    </section>
  );
}
