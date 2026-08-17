"""Deployment-owned approver authorization, separate from provider mechanics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from stateback.domain.enums import PrincipalType
from stateback.domain.exceptions import ContractValidationError
from stateback.domain.operation import Operation
from stateback.domain.policy import Approval
from stateback.domain.refs import PrincipalRef


@runtime_checkable
class ApproverAuthorizer(Protocol):
    def is_authorized(
        self,
        *,
        actor: PrincipalRef,
        operation: Operation,
        approval: Approval,
    ) -> bool: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfiguredApproverAuthorizer:
    allowed_principals: frozenset[tuple[PrincipalType, str]]

    def __post_init__(self) -> None:
        invalid = [
            principal_type
            for principal_type, _ in self.allowed_principals
            if principal_type not in {PrincipalType.HUMAN, PrincipalType.OPERATOR}
        ]
        if invalid:
            raise ContractValidationError(
                "invalid_approver_type",
                "configured approvers must be HUMAN or OPERATOR principals",
            )

    def is_authorized(
        self,
        *,
        actor: PrincipalRef,
        operation: Operation,
        approval: Approval,
    ) -> bool:
        del operation, approval
        return (actor.type, actor.id) in self.allowed_principals
