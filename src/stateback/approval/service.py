"""Authorized approval decisions through canonical transitions only."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session, sessionmaker

from stateback.approval.authorization import ApproverAuthorizer
from stateback.approval.commands import ApprovalDecisionCommand, ApprovalExpiryCommand
from stateback.approval.results import ApprovalDisposition, ApprovalResult
from stateback.domain.enums import ApprovalState
from stateback.domain.ids import OpaqueId
from stateback.domain.operation import Operation
from stateback.domain.policy import Approval
from stateback.domain.secrets import reject_secrets_in_str_map
from stateback.persistence.exceptions import ConcurrencyConflictError
from stateback.persistence.uow import unit_of_work
from stateback.runtime.clock import Clock
from stateback.transitions.commands import (
    ApprovalGrant,
    ApprovalReject,
    CancelAwaitingApproval,
)
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.results import TransitionOutcome
from stateback.transitions.service import TransitionService


class ApprovalService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        authorizer: ApproverAuthorizer,
        clock: Clock,
        transitions: TransitionService | None = None,
    ) -> None:
        self._factory = session_factory
        self._authorizer = authorizer
        self._clock = clock
        self._transitions = transitions or TransitionService()

    def decide(self, command: ApprovalDecisionCommand) -> ApprovalResult:
        if command.reason is not None:
            reject_secrets_in_str_map(
                (("reason", command.reason),), field="ApprovalDecisionCommand"
            )
        loaded = self._load(command)
        if loaded is None:
            return ApprovalResult(
                disposition=ApprovalDisposition.REJECTED,
                reason_code="not_found",
                operation=None,
                approval=None,
                transition=None,
            )
        operation, approval = loaded
        binding_error = self._binding_error(operation, approval)
        if binding_error is not None:
            return self._binding_rejected(operation, approval, binding_error)
        if not self._authorizer.is_authorized(
            actor=command.actor, operation=operation, approval=approval
        ):
            return ApprovalResult(
                disposition=ApprovalDisposition.UNAUTHORIZED,
                reason_code="approver_unauthorized",
                operation=operation,
                approval=approval,
                transition=None,
            )
        terminal = self._terminal_approval(approval, command)
        if approval.state is command.decision:
            return ApprovalResult(
                disposition=ApprovalDisposition.ACCEPTED,
                reason_code="already_applied",
                operation=operation,
                approval=approval,
                transition=None,
            )
        if approval.state is not ApprovalState.PENDING:
            return ApprovalResult(
                disposition=ApprovalDisposition.REJECTED,
                reason_code="approval_state_conflict",
                operation=operation,
                approval=approval,
                transition=None,
            )
        try:
            with unit_of_work(self._factory) as uow:
                result = self._transitions.apply(
                    uow, self._transition_command(command, terminal)
                )
        except ConcurrencyConflictError:
            return self._resolve_concurrent(command)
        if result.outcome is TransitionOutcome.REJECTED:
            return ApprovalResult(
                disposition=ApprovalDisposition.REJECTED,
                reason_code=result.reason_code,
                operation=result.operation,
                approval=approval,
                transition=result,
            )
        return ApprovalResult(
            disposition=ApprovalDisposition.ACCEPTED,
            reason_code="accepted",
            operation=result.operation,
            approval=terminal,
            transition=result,
        )

    def expire(self, command: ApprovalExpiryCommand) -> ApprovalResult:
        loaded = self._load_ids(command.operation_id, command.approval_id)
        if loaded is None:
            return ApprovalResult(
                disposition=ApprovalDisposition.REJECTED,
                reason_code="not_found",
                operation=None,
                approval=None,
                transition=None,
            )
        operation, approval = loaded
        binding_error = self._binding_error(operation, approval)
        if binding_error is not None:
            return self._binding_rejected(operation, approval, binding_error)
        if approval.state is ApprovalState.EXPIRED:
            return ApprovalResult(
                disposition=ApprovalDisposition.ACCEPTED,
                reason_code="already_applied",
                operation=operation,
                approval=approval,
                transition=None,
            )
        if approval.state is not ApprovalState.PENDING:
            return ApprovalResult(
                disposition=ApprovalDisposition.REJECTED,
                reason_code="approval_state_conflict",
                operation=operation,
                approval=approval,
                transition=None,
            )
        now = self._clock.now()
        if approval.expires_at is None or now.value < approval.expires_at.value:
            return ApprovalResult(
                disposition=ApprovalDisposition.REJECTED,
                reason_code="approval_not_expired",
                operation=operation,
                approval=approval,
                transition=None,
            )
        expired = replace(
            approval,
            state=ApprovalState.EXPIRED,
            decided_at=now,
            decided_by=None,
            reason="approval_expired",
        )
        try:
            with unit_of_work(self._factory) as uow:
                result = self._transitions.apply(
                    uow,
                    CancelAwaitingApproval(
                        kind=TransitionKind.CANCEL_AWAITING_APPROVAL,
                        operation_id=command.operation_id,
                        expected_version=command.expected_version,
                        occurred_at=now,
                        actor=None,
                        correlation_id=command.correlation_id,
                        reason_code="approval_expired",
                        transition_audit_event_id=command.transition_audit_event_id,
                        approval=expired,
                    ),
                )
        except ConcurrencyConflictError:
            refreshed = self._load_ids(command.operation_id, command.approval_id)
            if (
                refreshed is not None
                and self._binding_error(*refreshed) is None
                and refreshed[1].state is ApprovalState.EXPIRED
            ):
                return ApprovalResult(
                    disposition=ApprovalDisposition.ACCEPTED,
                    reason_code="already_applied",
                    operation=refreshed[0],
                    approval=refreshed[1],
                    transition=None,
                )
            return ApprovalResult(
                disposition=ApprovalDisposition.REJECTED,
                reason_code="concurrency_conflict",
                operation=operation,
                approval=approval,
                transition=None,
            )
        if result.outcome is TransitionOutcome.REJECTED:
            return ApprovalResult(
                disposition=ApprovalDisposition.REJECTED,
                reason_code=result.reason_code,
                operation=result.operation,
                approval=approval,
                transition=result,
            )
        return ApprovalResult(
            disposition=ApprovalDisposition.ACCEPTED,
            reason_code="accepted",
            operation=result.operation,
            approval=expired,
            transition=result,
        )

    def _load(
        self, command: ApprovalDecisionCommand
    ) -> tuple[Operation, Approval] | None:
        return self._load_ids(command.operation_id, command.approval_id)

    def _load_ids(
        self, operation_id: OpaqueId, approval_id: OpaqueId
    ) -> tuple[Operation, Approval] | None:
        with unit_of_work(self._factory) as uow:
            operation = uow.operations.get(operation_id)
            approval = uow.approvals.get(approval_id)
        if operation is None or approval is None:
            return None
        return operation, approval

    def _terminal_approval(
        self, approval: Approval, command: ApprovalDecisionCommand
    ) -> Approval:
        return replace(
            approval,
            state=command.decision,
            decided_at=self._clock.now(),
            decided_by=command.actor,
            reason=command.reason,
        )

    def _transition_command(
        self, command: ApprovalDecisionCommand, approval: Approval
    ) -> ApprovalGrant | ApprovalReject:
        if command.decision is ApprovalState.APPROVED:
            return ApprovalGrant(
                kind=TransitionKind.APPROVAL_GRANT,
                operation_id=command.operation_id,
                expected_version=command.expected_version,
                occurred_at=self._clock.now(),
                actor=command.actor,
                correlation_id=command.correlation_id,
                reason_code="approval_granted",
                transition_audit_event_id=command.ids.transition_audit_event_id,
                approval=approval,
                approval_audit_event_id=command.ids.approval_audit_event_id,
                outbox_event_id=command.ids.outbox_event_id,
            )
        return ApprovalReject(
            kind=TransitionKind.APPROVAL_REJECT,
            operation_id=command.operation_id,
            expected_version=command.expected_version,
            occurred_at=self._clock.now(),
            actor=command.actor,
            correlation_id=command.correlation_id,
            reason_code="approval_rejected",
            transition_audit_event_id=command.ids.transition_audit_event_id,
            approval=approval,
            approval_audit_event_id=command.ids.approval_audit_event_id,
        )

    def _resolve_concurrent(self, command: ApprovalDecisionCommand) -> ApprovalResult:
        loaded = self._load(command)
        if loaded is None:
            return ApprovalResult(
                disposition=ApprovalDisposition.REJECTED,
                reason_code="not_found",
                operation=None,
                approval=None,
                transition=None,
            )
        operation, approval = loaded
        binding_error = self._binding_error(operation, approval)
        if binding_error is not None:
            return self._binding_rejected(operation, approval, binding_error)
        if approval.state is command.decision:
            return ApprovalResult(
                disposition=ApprovalDisposition.ACCEPTED,
                reason_code="already_applied",
                operation=operation,
                approval=approval,
                transition=None,
            )
        return ApprovalResult(
            disposition=ApprovalDisposition.REJECTED,
            reason_code="concurrency_conflict",
            operation=operation,
            approval=approval,
            transition=None,
        )

    @staticmethod
    def _binding_error(operation: Operation, approval: Approval) -> str | None:
        if approval.operation_id != operation.operation_id:
            return "approval_operation_mismatch"
        if operation.current_approval_id != approval.approval_id:
            return "approval_not_current"
        if approval.intent_digest != operation.intent.intent_digest:
            return "approval_intent_mismatch"
        if operation.current_policy_decision_id != approval.policy_decision_id:
            return "approval_policy_mismatch"
        if approval.state is ApprovalState.PENDING:
            if approval.operation_version != operation.version:
                return "approval_version_mismatch"
        elif operation.version <= approval.operation_version:
            return "approval_version_mismatch"
        return None

    @staticmethod
    def _binding_rejected(
        operation: Operation, approval: Approval, reason_code: str
    ) -> ApprovalResult:
        return ApprovalResult(
            disposition=ApprovalDisposition.REJECTED,
            reason_code=reason_code,
            operation=operation,
            approval=approval,
            transition=None,
        )
