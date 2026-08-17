"""Verification/reconciliation service. Importing this package MUST NOT open sockets."""

from __future__ import annotations

from stateback.recovery.budget import (
    PHASE6_DEFAULT_RECOVERY_ATTEMPTS,
    completed_original_verification_count,
    max_automatic_recovery_attempts,
)
from stateback.recovery.clock import Clock
from stateback.recovery.commands import (
    RECOVERY_ACTOR,
    OperatorVerificationCommand,
    RecoveryCommand,
    RecoveryIdFactory,
    ScanCommand,
)
from stateback.recovery.exceptions import SimulatedRecoveryCrash, StatebackRecoveryError
from stateback.recovery.faults import RecoveryCrashPoint
from stateback.recovery.ids import RecoveryIds
from stateback.recovery.kinds import RecoveryKindDecision, decision_to_kind
from stateback.recovery.reconcile import reconcile
from stateback.recovery.request import build_original_verification_request
from stateback.recovery.results import RecoveryDisposition, RecoveryResult
from stateback.recovery.service import RecoveryService

__all__ = [
    "Clock",
    "OperatorVerificationCommand",
    "PHASE6_DEFAULT_RECOVERY_ATTEMPTS",
    "RECOVERY_ACTOR",
    "RecoveryCommand",
    "RecoveryCrashPoint",
    "RecoveryDisposition",
    "RecoveryIdFactory",
    "RecoveryIds",
    "RecoveryKindDecision",
    "RecoveryResult",
    "RecoveryService",
    "ScanCommand",
    "SimulatedRecoveryCrash",
    "StatebackRecoveryError",
    "build_original_verification_request",
    "completed_original_verification_count",
    "decision_to_kind",
    "max_automatic_recovery_attempts",
    "reconcile",
]
