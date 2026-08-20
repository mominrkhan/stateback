"""Stateback package root.

Phase 7 adds compensation (`stateback.compensation`) as a first-class side
effect on top of Phases 1-6. This module MUST NOT open sockets, connect to
PostgreSQL, or import runtime/policy/providers/recovery/compensation.
"""

__version__ = "0.1.0"
