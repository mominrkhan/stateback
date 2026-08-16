from __future__ import annotations

import pytest

from stateback.domain.enums import WorkCommand
from stateback.transitions.kinds import TransitionKind
from stateback.transitions.outbox import OUTBOX_COMMAND_FOR_KIND

pytestmark = pytest.mark.unit


def test_policy_allow_maps_execute() -> None:
    assert OUTBOX_COMMAND_FOR_KIND[TransitionKind.POLICY_ALLOW] is WorkCommand.EXECUTE


def test_claim_execution_has_no_outbox() -> None:
    assert TransitionKind.CLAIM_EXECUTION not in OUTBOX_COMMAND_FOR_KIND


def test_execution_unknown_maps_verify() -> None:
    assert (
        OUTBOX_COMMAND_FOR_KIND[TransitionKind.EXECUTION_UNKNOWN] is WorkCommand.VERIFY
    )


def test_unmapped_kind_not_in_dict() -> None:
    assert TransitionKind.POLICY_DENY not in OUTBOX_COMMAND_FOR_KIND
    assert TransitionKind.VERIFICATION_INCONCLUSIVE not in OUTBOX_COMMAND_FOR_KIND
    assert TransitionKind.COMPENSATION_APPLIED not in OUTBOX_COMMAND_FOR_KIND


def test_create_has_no_outbox() -> None:
    assert TransitionKind.CREATE_OPERATION not in OUTBOX_COMMAND_FOR_KIND
