"""ProcessService — PID lookup via libproc + child PID registry."""

from __future__ import annotations

import threading

from claudewatch.backend.core.base_service import BaseService
from claudewatch.backend.core.process import procinfo


class ProcessService(BaseService):
    """Wraps libproc process inspection and manages child PID tracking.

    The child PID registry tracks PIDs of subprocesses we spawn (e.g.
    ``claude -p`` for summary generation) so the detection layer can
    filter them out of session results.
    """

    def __init__(self) -> None:
        super().__init__()
        self._child_pids: set[int] = set()
        self._child_pids_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Process inspection (delegates to procinfo)
    # ------------------------------------------------------------------

    def list_all(self) -> list[dict]:
        """Return pid, ppid, tty, comm for every process on the system."""
        return procinfo.list_all_processes()

    def get_info(self, pids: list[int]) -> dict[int, dict]:
        """Get tty, ppid, and full executable path for a list of PIDs."""
        return procinfo.get_process_info(pids)

    def get_cwds(self, pids: list[int]) -> dict[int, str]:
        """Get the current working directory for a list of PIDs."""
        return procinfo.get_cwds(pids)

    def get_ppid(self, pid: int) -> int:
        """Get the parent PID for a single process. Returns 0 on failure."""
        return procinfo.get_ppid(pid)

    def get_single_info(self, pid: int) -> dict | None:
        """Get tty, ppid, and comm for a single PID. Returns None on failure."""
        return procinfo.get_single_process_info(pid)

    # ------------------------------------------------------------------
    # Child PID registry
    # ------------------------------------------------------------------

    def register_child(self, pid: int) -> None:
        """Add a PID to the child process registry."""
        with self._child_pids_lock:
            self._child_pids.add(pid)

    def unregister_child(self, pid: int) -> None:
        """Remove a PID from the child process registry."""
        with self._child_pids_lock:
            self._child_pids.discard(pid)

    def get_child_pids(self) -> set[int]:
        """Return a snapshot of registered child PIDs."""
        with self._child_pids_lock:
            return set(self._child_pids)
