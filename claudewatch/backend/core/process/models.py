"""Typed models for process inspection data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessInfo:
    """Process info from libproc: tty, parent PID, and executable path."""

    tty: str
    ppid: int
    comm: str


@dataclass(frozen=True)
class ProcessEntry:
    """Full process entry including PID, for list_all_processes results."""

    pid: int
    tty: str
    ppid: int
    comm: str
