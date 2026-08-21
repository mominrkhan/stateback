import type { JsonValue, Reconstruction } from "../../api/types";
import { CopyableId } from "../../components/CopyableId";
import { Timestamp } from "../../components/Timestamp";
import { EmptyDetail, Principal } from "./detailUtils";

function jsonRecord(value: JsonValue): Record<string, JsonValue> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : null;
}

function safeString(record: Record<string, JsonValue>, key: string): string | null {
  return typeof record[key] === "string" ? record[key] : null;
}

function safeStrings(record: Record<string, JsonValue>, key: string): string[] | null {
  const value = record[key];
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : null;
}

function GitHubCreateIssueReview({ reconstruction }: { reconstruction: Reconstruction }) {
  const { intent } = reconstruction.operation;
  const effect = intent.effect;
  if (effect.provider !== "github" || effect.action !== "create_issue" || effect.version !== "v1") return null;
  const args = jsonRecord(intent.arguments);
  if (!args) return null;
  const body = safeString(args, "body");
  const allowed = [
    ["Owner", safeString(args, "owner")],
    ["Repository", safeString(args, "repo")],
    ["Title", safeString(args, "title")],
    ["Labels", safeStrings(args, "labels")?.join(", ") ?? null],
    ["Assignees", safeStrings(args, "assignees")?.join(", ") ?? null],
  ] as const;

  return (
    <section aria-labelledby="github-review-heading">
      <h3 id="github-review-heading">GitHub issue review</h3>
      <dl>
        {allowed.flatMap(([label, value]) => value === null ? [] : [
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>,
        ])}
        {body !== null && (
          <div>
            <dt>Body</dt>
            <dd>{body.length} characters / {new TextEncoder().encode(body).length} bytes; content withheld</dd>
          </div>
        )}
        <div><dt>Intent digest</dt><dd><CopyableId value={intent.intent_digest} label="intent digest" /></dd></div>
      </dl>
    </section>
  );
}

export function SummaryPanel({ reconstruction }: { reconstruction: Reconstruction }) {
  const { operation, policy_decisions: policyDecisions, approvals } = reconstruction;
  return (
    <section aria-labelledby="summary-heading">
      <h2 id="summary-heading">Summary</h2>
      <dl>
        <div><dt>Risk</dt><dd>{operation.risk_level}</dd></div>
        <div><dt>Intent digest</dt><dd><CopyableId value={operation.intent.intent_digest} label="intent digest" /></dd></div>
        <div><dt>Requested by</dt><dd><Principal principal={operation.intent.requester} /></dd></div>
        <div><dt>Requested</dt><dd><Timestamp value={operation.intent.requested_at} /></dd></div>
        <div><dt>Backend available actions</dt><dd>{reconstruction.available_actions.join(", ") || "None"}</dd></div>
        <div><dt>Latest audit reason</dt><dd>{reconstruction.audit.at(-1)?.reason_code ?? "Not recorded"}</dd></div>
      </dl>
      <GitHubCreateIssueReview reconstruction={reconstruction} />
      <section aria-labelledby="policy-heading">
        <h3 id="policy-heading">Policy decisions</h3>
        {policyDecisions.length === 0 ? <EmptyDetail>No policy decision is present in this reconstruction.</EmptyDetail> : (
          <ol>
            {policyDecisions.map((decision) => (
              <li key={decision.policy_decision_id}>
                <strong>{decision.verdict}</strong> — {decision.reason_codes.join(", ") || "No reason code"}
                {decision.explanation && <p>{decision.explanation}</p>}
                <p>Revision {decision.policy_revision}; evaluated <Timestamp value={decision.evaluated_at} /></p>
                <dl>
                  <div><dt>Verification required</dt><dd>{decision.obligations.require_verification ? "Yes" : "No"}</dd></div>
                  <div><dt>Automatic compensation allowed</dt><dd>{decision.obligations.automatic_compensation_allowed ? "Yes" : "No"}</dd></div>
                  <div><dt>Operator reason required</dt><dd>{decision.obligations.operator_reason_required ? "Yes" : "No"}</dd></div>
                </dl>
              </li>
            ))}
          </ol>
        )}
      </section>
      <section aria-labelledby="approvals-heading">
        <h3 id="approvals-heading">Approvals</h3>
        {approvals.length === 0 ? <EmptyDetail>No approval is present in this reconstruction.</EmptyDetail> : (
          <ol>
            {approvals.map((approval) => (
              <li key={approval.approval_id}>
                <CopyableId value={approval.approval_id} label="approval ID" />
                <p>State: {approval.state}; requested <Timestamp value={approval.requested_at} /></p>
                {approval.decided_by && <p>Decided by <Principal principal={approval.decided_by} /></p>}
                {approval.reason && <p>Reason: {approval.reason}</p>}
              </li>
            ))}
          </ol>
        )}
      </section>
    </section>
  );
}
