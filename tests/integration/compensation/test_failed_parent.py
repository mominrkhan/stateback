from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy.orm import Session, sessionmaker

from stateback.compensation.results import CompensationDisposition
from stateback.compensation.service import CompensationService
from stateback.domain.enums import ErrorKind, OperationState
from stateback.policy.evaluation import PHASE5_DEFAULT_OBLIGATIONS
from tests.integration.compensation.conftest import (
    build_failed_operation_with_artifact,
    make_start,
)
from tests.integration.compensation.idseq import IdSeq

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_failed_without_artifact_not_eligible(
    uow_factory: sessionmaker[Session],
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    op = build_failed_operation_with_artifact(
        uow_factory,
        seq,
        external_operation_id=None,
        external_resource_ids=(),
    )
    result = compensation.start(make_start(seq, op.operation_id, op.version))
    assert result.disposition is CompensationDisposition.NOT_ELIGIBLE
    assert result.reason_code == "failed_without_artifact"
    assert result.operation is not None
    assert result.operation.state is OperationState.FAILED


def test_failed_with_artifact_and_automatic_true_starts(
    uow_factory: sessionmaker[Session],
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    obligations = dataclasses.replace(
        PHASE5_DEFAULT_OBLIGATIONS, automatic_compensation_allowed=True
    )
    op = build_failed_operation_with_artifact(
        uow_factory,
        seq,
        external_operation_id="ext-failed-1",
        obligations=obligations,
    )
    result = compensation.start(
        make_start(seq, op.operation_id, op.version, automatic=True)
    )
    assert result.disposition is CompensationDisposition.ACCEPTED
    assert result.operation is not None
    assert result.operation.state is OperationState.COMPENSATING
    assert result.compensation is not None


def test_failed_clean_reject_does_not_start(
    uow_factory: sessionmaker[Session],
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    op = build_failed_operation_with_artifact(
        uow_factory,
        seq,
        external_operation_id="ext-failed-1",
        error_kind=ErrorKind.VALIDATION,
    )
    result = compensation.start(make_start(seq, op.operation_id, op.version))
    assert result.disposition is CompensationDisposition.NOT_ELIGIBLE
    assert result.reason_code == "failed_without_artifact"
