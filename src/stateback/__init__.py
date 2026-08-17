"""Stateback package root.

Phase 6 adds verification/reconciliation (`stateback.recovery`) on top of
the Phase 5 synchronous kernel. This module MUST NOT open sockets, connect
to PostgreSQL, or import runtime/policy/providers/recovery.
"""

__version__ = "0.0.0"
