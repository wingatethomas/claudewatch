"""Edit-to-function mapper — links Action(edit) nodes to Symbol nodes."""

from __future__ import annotations

import logging
import os

import kuzu

log = logging.getLogger("claudewatch")


class EditMapper:
    """Maps edit actions to the symbols they modified."""

    def __init__(self, conn: kuzu.Connection) -> None:
        self._conn = conn

    def map_all(self) -> int:
        """Find unmapped edit actions and link them to symbols. Returns count mapped."""
        result = self._safe_execute(
            "MATCH (a:Action {kind: 'edit'}) "
            "WHERE NOT (a)-[:MODIFIES]->() AND a.file_path <> '' "
            "RETURN a.id, a.file_path, a.new_text, a.old_text",
        )
        if not result:
            return 0

        count = 0
        while result.has_next():
            row = result.get_next()
            action_id, file_path, new_text, old_text = row
            if self._map_one(action_id, file_path, new_text or "", old_text or ""):
                count += 1
        return count

    def _map_one(
        self,
        action_id: str,
        file_path: str,
        new_text: str,
        old_text: str,
    ) -> bool:
        """Map a single edit to the innermost symbol containing it."""
        line_num = self._find_edit_line(file_path, new_text, old_text)
        if line_num is None:
            return False

        # Find symbols in this file that contain this line
        result = self._safe_execute(
            "MATCH (sym:Symbol) "
            "WHERE sym.file_path = $fp AND sym.start_line <= $line AND sym.end_line >= $line "
            "RETURN sym.id, sym.kind, sym.start_line, sym.end_line "
            "ORDER BY (sym.end_line - sym.start_line) ASC",
            {"fp": file_path, "line": line_num},
        )
        if not result or not result.has_next():
            return False

        # Pick innermost symbol (smallest range)
        symbol_id = result.get_next()[0]
        self._safe_execute(
            "MATCH (a:Action {id: $aid}), (sym:Symbol {id: $sid}) MERGE (a)-[:MODIFIES]->(sym)",
            {"aid": action_id, "sid": symbol_id},
        )
        return True

    _MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

    def _find_edit_line(self, file_path: str, new_text: str, old_text: str) -> int | None:  # noqa: PLR0911
        """Find the line number of an edit in the current file."""
        if not os.path.isfile(file_path):
            return None
        try:
            if os.path.getsize(file_path) > self._MAX_FILE_SIZE:
                return None
            with open(file_path) as f:
                content = f.read()
        except OSError:
            return None

        # Try finding new_text first (post-edit state)
        search_text = new_text if new_text else old_text
        if not search_text:
            return None

        # Find the first line of the search text in the file
        first_line = search_text.split("\n")[0].strip()
        if not first_line:
            return None

        for i, line in enumerate(content.split("\n"), 1):
            if first_line in line:
                return i

        # Fall back to old_text if new_text wasn't found
        if new_text and old_text:
            first_line = old_text.split("\n", maxsplit=1)[0].strip()
            if first_line:
                for i, line in enumerate(content.split("\n"), 1):
                    if first_line in line:
                        return i

        return None

    def _safe_execute(self, query: str, params: dict[str, object] | None = None) -> kuzu.QueryResult | None:
        try:
            return self._conn.execute(query, params or {})
        except RuntimeError:
            log.debug("mapper query failed: %s", query[:80])
            return None
