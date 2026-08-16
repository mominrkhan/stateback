"""Synchronous execution kernel. Importing this package MUST NOT open sockets."""

from __future__ import annotations

from stateback.runtime.attempt import build_completed_attempt, build_started_attempt
from stateback.runtime.clock import Clock
from stateback.runtime.commands import (
    PHASE5_ENVIRONMENT,
    ExecuteCommand,
    RecoverCommand,
    SubmitCommand,
)
from stateback.runtime.exceptions import SimulatedCrash
from stateback.runtime.faults import RuntimeCrashPoint
from stateback.runtime.ids import ExecuteIds, RecoverIds, SubmitIds
from stateback.runtime.outcome import decide_execution_kind, max_automatic_attempts
from stateback.runtime.recover import RECOVERY_ACTOR
from stateback.runtime.results import RuntimeDisposition, RuntimeResult
from stateback.runtime.service import SynchronousRuntime

__all__ = [
    "Clock",
    "ExecuteCommand",
    "ExecuteIds",
    "PHASE5_ENVIRONMENT",
    "RECOVERY_ACTOR",
    "RecoverCommand",
    "RecoverIds",
    "RuntimeCrashPoint",
    "RuntimeDisposition",
    "RuntimeResult",
    "SimulatedCrash",
    "SubmitCommand",
    "SubmitIds",
    "SynchronousRuntime",
    "build_completed_attempt",
    "build_started_attempt",
    "decide_execution_kind",
    "max_automatic_attempts",
]
