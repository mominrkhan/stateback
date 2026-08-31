import type { Meta, StoryObj } from "@storybook/react-vite";
import type { Operation } from "../../api/types";
import { OperationTable } from "./OperationTable";

const operation: Operation = { contract_version: "v1", operation_id: "01JSTATEBACKEXAMPLE", state: "UNKNOWN", version: 3, intent: { effect: { provider: "github", action: "create_pull_request", version: "v1" }, arguments_mode: "INLINE", arguments: { owner: "mominrkhan", repo: "stateback", head: "feature/sdk", base: "main", title: "Add SDK boundary" }, arguments_ref: null, canonical_arguments_hash: "hash", intent_digest: "digest", requester: { type: "AGENT", id: "coding-agent", display_name: "Coding agent" }, requested_at: "2026-08-30T12:00:00Z", metadata: {} }, risk_level: "MODERATE", idempotency_identity: "identity", current_policy_decision_id: null, current_approval_id: null, latest_attempt_id: null, latest_verification_id: null, compensation_id: null, created_at: "2026-08-30T12:00:00Z", updated_at: "2026-08-30T12:02:00Z" };

const meta = { title: "Stateback/Operation row", component: OperationTable, args: { operations: [operation, { ...operation, operation_id: "01JSTATEBACKSUCCESS", state: "SUCCEEDED" }], onNavigate: () => undefined } } satisfies Meta<typeof OperationTable>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Default: Story = {};
export const LifecycleStates: Story = { args: { operations: [
  operation,
  { ...operation, operation_id: "01JSTATEBACKSUCCESS", state: "SUCCEEDED" },
  { ...operation, operation_id: "01JSTATEBACKFAILED", state: "FAILED" },
  { ...operation, operation_id: "01JSTATEBACKVERIFYING", state: "VERIFYING" },
] } };
export const Narrow: Story = { parameters: { viewport: { defaultViewport: "mobile1" } } };
