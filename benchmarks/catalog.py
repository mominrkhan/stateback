"""Phase 17 reuses existing evidence rather than weakening or duplicating it."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectnessScenario:
    name: str
    node_id: str
    final_truth: str


SCENARIOS: tuple[CorrectnessScenario, ...] = (
    CorrectnessScenario(
        name="crash_before_provider",
        node_id="tests/integration/runtime/test_crash_boundaries.py",
        final_truth="PostgreSQL operation/attempt/audit and reference external store",
    ),
    CorrectnessScenario(
        name="lost_provider_response",
        node_id="tests/integration/recovery/test_applied_after_lost_response.py",
        final_truth="reconciled PostgreSQL state and external store",
    ),
    CorrectnessScenario(
        name="verification_transport_failure",
        node_id="tests/integration/recovery/test_transport.py",
        final_truth="unknown remains durable across verification transport failure",
    ),
    CorrectnessScenario(
        name="verification_malformed_or_inconsistent",
        node_id="tests/integration/recovery/test_malformed_inconsistent.py",
        final_truth="malformed/inconsistent verification evidence and manual recovery state",
    ),
    CorrectnessScenario(
        name="reconciliation_inconclusive",
        node_id="tests/integration/recovery/test_inconclusive.py",
        final_truth="durable verification and reconciliation decision history",
    ),
    CorrectnessScenario(
        name="operator_verification",
        node_id="tests/integration/recovery/test_operator.py",
        final_truth="capability-legal verification and attributable operator audit",
    ),
    CorrectnessScenario(
        name="concurrent_execution",
        node_id="tests/integration/runtime/test_concurrency.py",
        final_truth="single compatible durable claim and external effect",
    ),
    CorrectnessScenario(
        name="duplicate_redelivery",
        node_id="tests/integration/runtime/test_messaging_runtime.py",
        final_truth="PostgreSQL reload decision and durable acknowledgement safety",
    ),
    CorrectnessScenario(
        name="policy_approval",
        node_id="tests/integration/runtime/test_policy_approval_control.py",
        final_truth="intent-bound approval, operation state, audit, and outbox",
    ),
    CorrectnessScenario(
        name="github_provider_faults",
        node_id="tests/contract/test_github_adapter_v1.py",
        final_truth="normalized evidence and honest provider capability",
    ),
    CorrectnessScenario(
        name="public_api_and_idempotency",
        node_id="tests/integration/runtime/test_application_service.py",
        final_truth="durable operation, deterministic audit, and caller isolation",
    ),
    CorrectnessScenario(
        name="malicious_mcp_input",
        node_id="tests/unit/mcp/test_tools.py",
        final_truth="no application call and no provider/shell bypass",
    ),
    CorrectnessScenario(
        name="compensation_operator_controls",
        node_id="tests/integration/compensation/test_operator.py",
        final_truth="legal operator action, rejection, and attributable audit evidence",
    ),
    CorrectnessScenario(
        name="compensation_crash_boundaries",
        node_id="tests/integration/compensation/test_crash_boundaries.py",
        final_truth="durable compensation intent/attempt state across crashes",
    ),
    CorrectnessScenario(
        name="compensation_concurrency",
        node_id="tests/integration/compensation/test_concurrency.py",
        final_truth="single compatible compensation claim and external effect",
    ),
    CorrectnessScenario(
        name="compensation_verification",
        node_id="tests/integration/compensation/test_verification.py",
        final_truth="verification-backed compensation convergence",
    ),
    CorrectnessScenario(
        name="compensation_unknown",
        node_id="tests/integration/compensation/test_unknown.py",
        final_truth="ambiguous compensation remains unknown pending reconciliation",
    ),
    CorrectnessScenario(
        name="compensation_not_applied",
        node_id="tests/integration/compensation/test_not_applied.py",
        final_truth="failed compensation and durable provider evidence",
    ),
    CorrectnessScenario(
        name="operator_frontend_behavior",
        node_id="frontend/src/app/App.test.tsx",
        final_truth="backend-derived state, confirmation, and safe unknown rendering",
    ),
)
