"""BookmarkService — facade over the bookmarks repository for UI consumption."""

from claudewatch.backend.bookmark import repository as bookmarks_repo
from claudewatch.backend.core.dto import PinDTO
from claudewatch.backend.core.service import BaseService


class BookmarkService(BaseService):
    """Pin/unpin sessions and return DTOs for the UI layer."""

    def pin(self, session_id: str, project: str, cwd: str, note: str) -> None:
        """Pin a session with a note. Updates if already pinned."""
        bookmarks_repo.pin_session(session_id, project, cwd, note)

    def unpin(self, cwd: str) -> None:
        """Unpin a session by CWD."""
        bookmarks_repo.unpin_session(cwd)

    def get_pins(self) -> list[PinDTO]:
        """Return all pinned sessions as DTOs."""
        return [
            PinDTO(
                session_id=p.get("session_id", ""),
                project=p.get("project", ""),
                cwd=p.get("cwd", ""),
                note=p.get("note", ""),
                timestamp=p.get("timestamp", ""),
            )
            for p in bookmarks_repo.get_pins()
        ]

    def get_pinned_cwds(self) -> set[str]:
        """Return the set of CWDs that are currently pinned."""
        return bookmarks_repo.get_pinned_cwds()

    def clear_all(self) -> None:
        """Delete all bookmarks."""
        bookmarks_repo._save([])
