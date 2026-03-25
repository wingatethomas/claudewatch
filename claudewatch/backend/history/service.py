"""HistoryService — facade over the history repository for UI consumption."""

from claudewatch.backend.core.dto import HistoryEntryDTO
from claudewatch.backend.core.service import BaseService
from claudewatch.backend.history import repository as history_repo


class HistoryService(BaseService):
    """Record, list, and remove session history entries as DTOs."""

    def record(self, session_id: str, project: str, cwd: str, model: str, host_app: str) -> None:
        """Record a session when it ends."""
        history_repo.record_session(session_id, project, cwd, model, host_app)

    def get_all(self) -> list[HistoryEntryDTO]:
        """Return all history entries as DTOs, newest first."""
        return [
            HistoryEntryDTO(
                session_id=e.get("session_id", ""),
                project=e.get("project", ""),
                cwd=e.get("cwd", ""),
                model=e.get("model", ""),
                host_app=e.get("host_app", ""),
                ended_at=e.get("ended_at", ""),
            )
            for e in history_repo.get_history()
        ]

    def remove(self, cwd: str) -> None:
        """Remove a history entry by CWD."""
        history_repo.remove_history_entry(cwd)
