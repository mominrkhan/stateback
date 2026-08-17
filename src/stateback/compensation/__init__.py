"""Compensation service. Importing this package MUST NOT open sockets."""

from __future__ import annotations

from stateback.compensation.commands import (
    COMPENSATION_ACTOR,
    CompensationIdFactory,
    ExecuteCompensationCommand,
    OperatorCompensationCommand,
    RecoverCompensationCommand,
    ScanCompensationCommand,
    StartCompensationCommand,
)
from stateback.compensation.eligibility import (
    EligibilityDecision,
    evaluate_start_eligibility,
)
from stateback.compensation.exceptions import (
    SimulatedCompensationCrash,
    StatebackCompensationError,
)
from stateback.compensation.faults import CompensationCrashPoint
from stateback.compensation.ids import (
    CompensationIds,
    CompensationRetryIdFactory,
    CompensationRetryIds,
)
from stateback.compensation.intent import compute_compensation_intent_digest
from stateback.compensation.kinds import compensation_decision_to_kind
from stateback.compensation.outcome import decide_compensate_kind
from stateback.compensation.reconcile import reconcile_compensation
from stateback.compensation.results import CompensationDisposition, CompensationResult
from stateback.compensation.service import CompensationService
from stateback.runtime.clock import Clock

__all__ = [
    "COMPENSATION_ACTOR",
    "Clock",
    "CompensationCrashPoint",
    "CompensationDisposition",
    "CompensationIdFactory",
    "CompensationIds",
    "CompensationRetryIdFactory",
    "CompensationRetryIds",
    "CompensationResult",
    "CompensationService",
    "EligibilityDecision",
    "ExecuteCompensationCommand",
    "OperatorCompensationCommand",
    "RecoverCompensationCommand",
    "ScanCompensationCommand",
    "SimulatedCompensationCrash",
    "StartCompensationCommand",
    "StatebackCompensationError",
    "compute_compensation_intent_digest",
    "decide_compensate_kind",
    "evaluate_start_eligibility",
    "reconcile_compensation",
    "compensation_decision_to_kind",
]
