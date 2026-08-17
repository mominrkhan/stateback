from __future__ import annotations

from pathlib import Path

import pytest
from benchmarks.catalog import SCENARIOS

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).resolve().parents[3]


def test_catalog_targets_exist_and_cover_product_seam() -> None:
    names = {scenario.name for scenario in SCENARIOS}
    assert {
        "crash_before_provider",
        "lost_provider_response",
        "verification_transport_failure",
        "reconciliation_inconclusive",
        "concurrent_execution",
        "duplicate_redelivery",
        "github_provider_faults",
        "public_api_and_idempotency",
        "malicious_mcp_input",
        "compensation_crash_boundaries",
        "compensation_unknown",
        "operator_frontend_behavior",
    } <= names
    for scenario in SCENARIOS:
        assert (_ROOT / scenario.node_id).exists(), scenario.node_id
        assert scenario.final_truth
        if scenario.node_id.startswith("tests/"):
            assert "benchmark_correctness" in (_ROOT / scenario.node_id).read_text(
                encoding="utf-8"
            )


def test_methodology_constants_are_frozen() -> None:
    source = (_ROOT / "benchmarks" / "run.py").read_text(encoding="utf-8")
    assert 'BENCHMARK_VERSION = "sb-bench-v1"' in source
    assert "DEFAULT_SEED = 1709" in source
    assert "DEFAULT_WARMUPS = 5" in source
    assert "DEFAULT_REPETITIONS = 30" in source
    assert "raw_measurements_ns" in source
    assert "source_tree_sha256" in source
    assert "STATEBACK_BENCH_TOKEN" in source
    assert '"token"' not in source
