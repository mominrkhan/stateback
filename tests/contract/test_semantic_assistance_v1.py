from __future__ import annotations

import json

import pytest

from stateback.semantic import AuditSummaryService, DeterministicSemanticModel
from tests.unit.application.fixtures import operation

pytestmark = [pytest.mark.contract, pytest.mark.unit]


def test_semantic_summary_v1_wire_contract_is_advisory() -> None:
    model = DeterministicSemanticModel(
        content=json.dumps(
            {
                "status": "AVAILABLE",
                "summary": "No audit events are available to interpret.",
                "key_events": [],
                "unresolved_uncertainties": ["No execution evidence exists"],
                "confidence": 0.75,
            }
        )
    )
    wire = (
        AuditSummaryService(semantic_model=model)
        .summarize(operation=operation(), audit=())
        .to_wire()
    )

    assert set(wire) == {
        "contract_version",
        "advisory",
        "status",
        "summary",
        "key_events",
        "unresolved_uncertainties",
        "confidence",
        "summarized_operation_version",
        "summarized_through_sequence",
        "provenance",
        "reason_code",
    }
    assert wire["contract_version"] == "v1"
    assert wire["advisory"] is True
    assert wire["summarized_operation_version"] == 2
    assert wire["summarized_through_sequence"] == 0
    assert wire["provenance"] == {
        "provider": "deterministic_fake",
        "model": "audit-summary-fixture-v1",
        "prompt_version": "audit-summary-v1",
        "output_schema_version": "v1",
    }
