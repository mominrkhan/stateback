from __future__ import annotations

from datetime import UTC, datetime

from stateback.domain.enums import (
    CONTRACT_VERSION,
    ArgumentsMode,
    PrincipalType,
    RiskLevel,
)
from stateback.domain.ids import OpaqueId
from stateback.domain.intent import IntentEnvelope
from stateback.domain.jsonutil import json_from_plain
from stateback.domain.refs import EffectRef, PrincipalRef
from stateback.domain.time import UtcTimestamp

TS = UtcTimestamp(value=datetime(2026, 8, 16, 19, 34, 0, tzinfo=UTC))
LATER = UtcTimestamp(value=datetime(2026, 8, 16, 19, 35, 0, tzinfo=UTC))

OP_ID = OpaqueId(value="00000000-0000-4000-8000-000000000001")
ATTEMPT_ID = OpaqueId(value="00000000-0000-4000-8000-000000000002")
POLICY_ID = OpaqueId(value="00000000-0000-4000-8000-000000000003")
APPROVAL_ID = OpaqueId(value="00000000-0000-4000-8000-000000000004")
VERIFY_ID = OpaqueId(value="00000000-0000-4000-8000-000000000005")
COMP_ID = OpaqueId(value="00000000-0000-4000-8000-000000000006")
COMP_ATTEMPT_ID = OpaqueId(value="00000000-0000-4000-8000-000000000007")
AUDIT_ID = OpaqueId(value="00000000-0000-4000-8000-000000000008")
OUTBOX_ID = OpaqueId(value="00000000-0000-4000-8000-000000000009")
MESSAGE_ID = OpaqueId(value="00000000-0000-4000-8000-00000000000a")

EFFECT = EffectRef(provider="reference", action="create_resource", version="v1")
REQUESTER = PrincipalRef(type=PrincipalType.AGENT, id="agent-1", display_name=None)
RISK = RiskLevel.MODERATE


def make_intent(
    *,
    arguments: object | None = None,
    metadata: tuple[tuple[str, str], ...] = (),
) -> IntentEnvelope:
    if arguments is None:
        arguments = {"name": "demo"}
    return IntentEnvelope.from_parts(
        effect=EFFECT,
        arguments_mode=ArgumentsMode.INLINE,
        arguments=json_from_plain(arguments),
        arguments_ref=None,
        requester=REQUESTER,
        requested_at=TS,
        metadata=metadata,
    )


assert CONTRACT_VERSION == "v1"
