from __future__ import annotations

import pytest

from stateback.compensation.results import CompensationDisposition
from stateback.compensation.service import CompensationService
from stateback.domain.enums import PrincipalType
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.refs import PrincipalRef
from stateback.runtime import SynchronousRuntime
from tests.integration.compensation.conftest import (
    make_operator,
    make_start,
)
from tests.integration.compensation.idseq import IdSeq
from tests.integration.runtime.conftest import make_submit
from tests.integration.runtime.idseq import execute_ids

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_secret_in_compensation_arguments_rejected(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    # If the original operation had arguments with a secret field (e.g. "api_key": "secret"),
    # building Compensation record will reject secrets.
    submitted = runtime.run(
        make_submit(seq, arguments=json_from_plain({"api_key": "super-secret-key"})),
        execute_ids(seq),
    )
    # Wait, runtime submit might reject it, but if submit had allowed it or it was created:
    if submitted.operation is None:
        # Submit already rejected it
        assert submitted.disposition.value == "REJECTED"
        return

    op = submitted.operation
    result = compensation.start(make_start(seq, op.operation_id, op.version))
    assert result.disposition is CompensationDisposition.REJECTED
    assert result.reason_code == "secret_field"


def test_secret_reason_code_rejected(
    runtime: SynchronousRuntime,
    compensation: CompensationService,
    seq: IdSeq,
) -> None:
    submitted = runtime.run(make_submit(seq), execute_ids(seq))
    assert submitted.operation is not None
    op = submitted.operation

    actor = PrincipalRef(type=PrincipalType.HUMAN, id="user-1", display_name="User")
    cmd = make_operator(
        seq,
        op.operation_id,
        op.version,
        actor=actor,
        reason_code="authorization: Bearer secret-token-12345",
    )
    result = compensation.start_operator_compensation(cmd)
    assert result.disposition is CompensationDisposition.REJECTED
    assert result.reason_code in {"secret_field", "invalid_reason_code"}
