import type { JsonValue, Operation } from "../api/types";
import { actionLabel, providerLabel, requesterLabel } from "./labels";

type ArgumentsRecord = Readonly<Record<string, JsonValue>>;

function asRecord(value: JsonValue): ArgumentsRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : null;
}
function text(record: ArgumentsRecord | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}
function positiveNumber(record: ArgumentsRecord | null, key: string): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
}

export interface OperationPresentation {
  action: string;
  provider: string;
  requester: string;
  primaryResource: string | null;
  secondaryResource: string | null;
  context: ReadonlyArray<{ label: string; value: string; mono?: boolean }>;
}

export function operationPresentation(operation: Operation): OperationPresentation {
  const args = operation.intent.effect.provider === "github" ? asRecord(operation.intent.arguments) : null;
  const owner = text(args, "owner");
  const repo = text(args, "repo");
  const repository = owner && repo ? `${owner}/${repo}` : null;
  const issue = positiveNumber(args, "issue_number");
  const pull = positiveNumber(args, "pull_number");
  const head = text(args, "head");
  const base = text(args, "base");
  const title = text(args, "title");
  const label = text(args, "label");
  const expectedHead = text(args, "head_sha");
  const mergeMethod = text(args, "merge_method");
  const action = operation.intent.effect.action;
  let primaryResource = repository;
  let secondaryResource: string | null = null;
  if (action === "create_issue" && title) secondaryResource = title;
  if (action === "create_issue_comment" && issue) secondaryResource = `Issue #${issue}`;
  if (action === "add_label" && issue) secondaryResource = `Issue #${issue}${label ? ` · ${label}` : ""}`;
  if (action === "create_pull_request") secondaryResource = head && base ? `${head} → ${base}` : title;
  if (action === "merge_pull_request" && pull) secondaryResource = `Pull request #${pull}`;

  const context: Array<{ label: string; value: string; mono?: boolean }> = [];
  if (repository) context.push({ label: "Repository", value: repository });
  if (title) context.push({ label: "Title", value: title });
  if (issue) context.push({ label: "Issue", value: `#${issue}` });
  if (pull) context.push({ label: "Pull request", value: `#${pull}` });
  if (head) context.push({ label: "Source", value: head });
  if (base) context.push({ label: "Base", value: base });
  if (expectedHead) context.push({ label: "Expected head", value: expectedHead, mono: true });
  if (mergeMethod) context.push({ label: "Merge method", value: mergeMethod });
  if (label) context.push({ label: "Label", value: label });

  return { action: actionLabel(operation.intent.effect), provider: providerLabel(operation.intent.effect.provider), requester: requesterLabel(operation.intent.requester), primaryResource, secondaryResource, context };
}
