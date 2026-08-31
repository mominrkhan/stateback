import type { Meta, StoryObj } from "@storybook/react-vite";

import type { OperatorClient } from "../api/client";
import { parseOperationPage, parseReconstruction } from "../api/parsers";
import type { OperatorOverview } from "../api/types";
import { ApprovalQueue } from "../features/approvals/ApprovalQueue";
import { LifecycleTimeline } from "../features/detail/LifecycleTimeline";
import { ProvidersPage } from "../features/providers/ProvidersPage";
import operationList from "../test/contract-fixtures/operation-list-v1.json";
import reconstructionFixture from "../test/contract-fixtures/reconstruction-verification-v1.json";

const operation = {
  ...parseOperationPage(structuredClone(operationList)).items[0],
  state: "AWAITING_APPROVAL",
};
const reconstruction = parseReconstruction(structuredClone(reconstructionFixture));
const overview: OperatorOverview = {
  contract_version: "v1",
  total_operations: 24,
  attention: { awaiting_approval: 1, unknown: 2, manual_intervention: 0, compensation_issues: 0 },
  active: { executing: 1, verifying: 1, compensating: 0 },
  recent_operations: [operation],
  providers: [{
    provider: "github",
    configured: false,
    supported_effects: [{ provider: "github", action: "create_issue", version: "v1" }],
  }],
};
const providerClient = { overview: async () => overview } as unknown as OperatorClient;

function Patterns() {
  return (
    <div style={{ display: "grid", gap: 28, width: "min(940px, 92vw)" }}>
      <ApprovalQueue operations={[operation]} selectedOperationId={operation.operation_id} onSelect={() => undefined} />
      <LifecycleTimeline reconstruction={reconstruction} />
      <ProvidersPage client={providerClient} />
    </div>
  );
}

const meta = { title: "Stateback/Operator patterns", component: Patterns } satisfies Meta<typeof Patterns>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ApprovalTimelineAndProvider: Story = {};
export const ApprovalCard: Story = { render: () => <div style={{ width: 420 }}><ApprovalQueue operations={[operation]} selectedOperationId={operation.operation_id} onSelect={() => undefined} /></div> };
export const TimelineItem: Story = { render: () => <div style={{ width: 680 }}><LifecycleTimeline reconstruction={reconstruction} /></div> };
export const ProviderCard: Story = { render: () => <div style={{ width: 820 }}><ProvidersPage client={providerClient} /></div> };
export const Narrow: Story = { parameters: { viewport: { defaultViewport: "mobile1" } } };
