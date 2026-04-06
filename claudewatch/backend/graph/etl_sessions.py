"""ETL pipeline 1: JSONL session logs → graph nodes and relationships."""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import uuid

import kuzu

from claudewatch.backend.core.paths import is_safe_projects_path

log = logging.getLogger("claudewatch")

_PR_PATTERN = re.compile(r"https?://github\.com/([^/]+/[^/]+)/pull/(\d+)")

# Checkpoint table lives in a separate SQLite DB (not worth graph nodes)
_CHECKPOINT_DDL = """
CREATE TABLE IF NOT EXISTS checkpoints (
    file_path TEXT PRIMARY KEY,
    byte_offset INTEGER DEFAULT 0,
    file_size INTEGER DEFAULT 0,
    file_mtime REAL DEFAULT 0
)
"""


class SessionETL:
    """Ingests JSONL session logs into the Kuzu graph."""

    def __init__(self, conn: kuzu.Connection, checkpoint_db: str) -> None:
        self._conn = conn
        self._ckpt = sqlite3.connect(checkpoint_db, check_same_thread=False)
        self._ckpt.execute(_CHECKPOINT_DDL)
        self._ckpt.commit()

    def ingest_all(self, projects_dir: str) -> dict[str, int]:
        """Process all JSONL files under the projects directory."""
        stats: dict[str, int] = {}
        if not os.path.isdir(projects_dir):
            return stats
        try:
            proj_keys = os.listdir(projects_dir)
        except OSError:
            return stats
        for proj_key in proj_keys:
            proj_dir = os.path.join(projects_dir, proj_key)
            if not os.path.isdir(proj_dir) or not is_safe_projects_path(proj_dir, projects_dir):
                continue
            try:
                files = [f for f in os.listdir(proj_dir) if f.endswith(".jsonl")]
            except OSError:
                continue
            for fname in files:
                path = os.path.join(proj_dir, fname)
                if not is_safe_projects_path(path, projects_dir):
                    continue
                session_id = fname.removesuffix(".jsonl")
                try:
                    count = self._process_file(path, session_id, proj_key)
                    if count > 0:
                        stats[session_id] = count
                except Exception:
                    log.exception("graph etl: error processing %s", path)
        return stats

    def _process_file(self, path: str, session_id: str, proj_key: str) -> int:
        try:
            stat = os.stat(path)
        except OSError:
            return 0

        mtime = stat.st_mtime
        size = stat.st_size

        row = self._ckpt.execute(
            "SELECT byte_offset, file_size, file_mtime FROM checkpoints WHERE file_path = ?",
            (path,),
        ).fetchone()
        byte_offset = 0
        if row:
            if row[2] == mtime and row[1] == size:
                return 0
            byte_offset = row[0]

        # Ensure project and session nodes exist
        project_path = _proj_key_to_path(proj_key)
        project_name = os.path.basename(project_path) if project_path != proj_key else proj_key
        self._merge_project(project_path, project_name)
        self._merge_session(session_id, project_path)

        count = 0
        new_offset = byte_offset
        prev_action_id: str | None = None

        try:
            with open(path, "rb") as f:
                f.seek(byte_offset)
                for line_bytes in f:
                    new_offset += len(line_bytes)
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if not isinstance(entry, dict):
                        continue
                    prev_action_id = self._process_entry(
                        entry,
                        session_id,
                        project_path,
                        prev_action_id,
                    )
                    count += 1
        except OSError:
            return 0

        self._ckpt.execute(
            "INSERT INTO checkpoints (file_path, byte_offset, file_size, file_mtime) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(file_path) DO UPDATE SET "
            "byte_offset=excluded.byte_offset, file_size=excluded.file_size, "
            "file_mtime=excluded.file_mtime",
            (path, new_offset, size, mtime),
        )
        self._ckpt.commit()
        return count

    def _process_entry(
        self,
        entry: dict,
        session_id: str,
        project_path: str,
        prev_action_id: str | None,
    ) -> str | None:
        """Process one JSONL entry. Returns the last action_id for NEXT chaining."""
        entry_type = entry.get("type", "")
        message = entry.get("message", {})
        if not isinstance(message, dict):
            return prev_action_id

        ts = entry.get("timestamp", "")

        if entry_type == "assistant":
            model = message.get("model", "")
            if model and model != "<synthetic>":
                self._update_session_model(session_id, model)

            # Extract token usage
            usage = message.get("usage", {})
            if isinstance(usage, dict) and usage:
                self._update_session_tokens(session_id, usage)

            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        action_id = self._process_tool(
                            block,
                            session_id,
                            project_path,
                            ts,
                        )
                        if action_id and prev_action_id:
                            self._create_next(prev_action_id, action_id)
                        if action_id:
                            prev_action_id = action_id
                    elif block.get("type") == "text":
                        self._extract_prs(block.get("text", ""), session_id, ts)

        # Check for agent spawns in the entry
        if entry.get("agentType"):
            self._process_agent(entry, session_id)

        return prev_action_id

    def _process_tool(
        self,
        block: dict,
        session_id: str,
        project_path: str,
        ts: str,
    ) -> str | None:
        tool_name = block.get("name", "")
        if not tool_name:
            return None
        tool_input = block.get("input", {})
        if not isinstance(tool_input, dict):
            tool_input = {}

        action_id = block.get("id") or str(uuid.uuid4())
        kind = _tool_to_kind(tool_name)
        file_path = ((tool_input.get("file_path") or tool_input.get("path")) or "")[:2048]
        command = (tool_input.get("command") or "")[:200] if kind == "bash" else ""
        pattern = tool_input.get("pattern", "") if kind == "search" else ""
        description = tool_input.get("description", "") if kind == "agent" else ""
        old_text = (tool_input.get("old_string") or "")[:500] if kind == "edit" else ""
        new_text = (tool_input.get("new_string") or "")[:500] if kind == "edit" else ""

        # Create Action node (param names prefixed to avoid Cypher keyword clashes)
        try:
            self._conn.execute(
                "MERGE (a:Action {id: $aid}) "
                "SET a.kind = $akind, a.session_id = $asid, a.file_path = $afp, "
                "a.timestamp = $ats, a.old_text = $aold, a.new_text = $anew, "
                "a.pattern = $apat, a.command = $acmd, a.description = $adesc",
                {
                    "aid": action_id,
                    "akind": kind,
                    "asid": session_id,
                    "afp": file_path,
                    "ats": ts,
                    "aold": old_text,
                    "anew": new_text,
                    "apat": pattern,
                    "acmd": command,
                    "adesc": description,
                },
            )
        except RuntimeError:
            log.debug("graph: failed to create Action %s", action_id)
            return None

        # PERFORMS edge: Session → Action
        self._safe_execute(
            "MATCH (s:Session {id: $sid}), (a:Action {id: $aid}) MERGE (s)-[:PERFORMS]->(a)",
            {"sid": session_id, "aid": action_id},
        )

        # TARGETS edge: Action → File
        if file_path:
            self._merge_file(file_path, project_path)
            self._safe_execute(
                "MATCH (a:Action {id: $aid}), (f:File {path: $fp}) MERGE (a)-[:TARGETS]->(f)",
                {"aid": action_id, "fp": file_path},
            )

        # Agent spawns
        if tool_name == "Agent":
            agent_id = action_id + "_agent"
            agent_type = tool_input.get("subagent_type", "general-purpose")
            self._safe_execute(
                "MERGE (ag:Agent {id: $agid}) "
                "SET ag.session_id = $asid, ag.agent_type = $atype, "
                "ag.description = $adesc, ag.status = 'active'",
                {"agid": agent_id, "asid": session_id, "atype": agent_type, "adesc": description},
            )
            self._safe_execute(
                "MATCH (s:Session {id: $sid}), (ag:Agent {id: $agid}) MERGE (s)-[:SPAWNS]->(ag)",
                {"sid": session_id, "agid": agent_id},
            )

        return action_id

    def _process_agent(self, entry: dict, session_id: str) -> None:
        agent_type = entry.get("agentType", "general-purpose")
        agent_id = entry.get("agentId", str(uuid.uuid4()))
        agent_desc = entry.get("description", "")
        self._safe_execute(
            "MERGE (ag:Agent {id: $agid}) "
            "SET ag.session_id = $asid, ag.agent_type = $atype, "
            "ag.description = $adesc, ag.status = 'active'",
            {"agid": agent_id, "asid": session_id, "atype": agent_type, "adesc": agent_desc},
        )
        self._safe_execute(
            "MATCH (s:Session {id: $sid}), (ag:Agent {id: $agid}) MERGE (s)-[:SPAWNS]->(ag)",
            {"sid": session_id, "agid": agent_id},
        )

    def _extract_prs(self, text: str, session_id: str, _ts: str) -> None:
        for match in _PR_PATTERN.finditer(text):
            repo = match.group(1)
            number = int(match.group(2))
            url = match.group(0)
            self._safe_execute(
                "MERGE (pr:PR {url: $url}) SET pr.number = $num, pr.repository = $repo",
                {"url": url, "num": number, "repo": repo},
            )
            self._safe_execute(
                "MATCH (s:Session {id: $sid}), (pr:PR {url: $url}) MERGE (s)-[:REFERENCES]->(pr)",
                {"sid": session_id, "url": url},
            )

    def _merge_project(self, path: str, name: str) -> None:
        self._safe_execute(
            "MERGE (p:Project {path: $path}) SET p.name = $name",
            {"path": path, "name": name},
        )

    def _merge_session(self, session_id: str, project_path: str) -> None:
        self._safe_execute(
            "MERGE (s:Session {id: $id}) SET s.project = $proj",
            {"id": session_id, "proj": project_path},
        )
        self._safe_execute(
            "MATCH (s:Session {id: $sid}), (p:Project {path: $pp}) MERGE (s)-[:IN_PROJECT]->(p)",
            {"sid": session_id, "pp": project_path},
        )

    def _merge_file(self, file_path: str, project_path: str) -> None:
        lang = _guess_language(file_path)
        self._safe_execute(
            "MERGE (f:File {path: $path}) SET f.project = $proj, f.language = $lang",
            {"path": file_path, "proj": project_path, "lang": lang},
        )
        self._safe_execute(
            "MATCH (p:Project {path: $pp}), (f:File {path: $fp}) MERGE (p)-[:HAS_FILE]->(f)",
            {"pp": project_path, "fp": file_path},
        )

    def _update_session_model(self, session_id: str, model: str) -> None:
        self._safe_execute(
            "MATCH (s:Session {id: $id}) SET s.model = $model",
            {"id": session_id, "model": model},
        )

    def _update_session_tokens(self, session_id: str, usage: dict) -> None:
        inp = usage.get("input_tokens", 0) or 0
        outp = usage.get("output_tokens", 0) or 0
        self._safe_execute(
            "MATCH (s:Session {id: $id}) "
            "SET s.input_tokens = coalesce(s.input_tokens, 0) + $inp, "
            "s.output_tokens = coalesce(s.output_tokens, 0) + $outp",
            {"id": session_id, "inp": inp, "outp": outp},
        )

    def _create_next(self, from_id: str, to_id: str) -> None:
        self._safe_execute(
            "MATCH (a1:Action {id: $from}), (a2:Action {id: $to}) MERGE (a1)-[:NEXT]->(a2)",
            {"from": from_id, "to": to_id},
        )

    def _safe_execute(self, query: str, params: dict | None = None) -> kuzu.QueryResult | None:
        try:
            return self._conn.execute(query, params or {})
        except RuntimeError:
            log.debug("graph query failed: %s", query[:80])
            return None

    def close(self) -> None:
        self._ckpt.close()


def _tool_to_kind(name: str) -> str:
    mapping = {
        "Read": "read",
        "Edit": "edit",
        "Write": "edit",
        "Bash": "bash",
        "Agent": "agent",
        "Grep": "search",
        "Glob": "search",
        "NotebookEdit": "edit",
    }
    return mapping.get(name, "other")


def _guess_language(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".rb": "ruby",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".swift": "swift",
        ".kt": "kotlin",
        ".md": "markdown",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".sh": "shell",
        ".sql": "sql",
    }
    return mapping.get(ext, "")


def _proj_key_to_path(proj_key: str) -> str:
    """Best-effort conversion of proj_key back to a path."""
    if proj_key.startswith("-"):
        return "/" + proj_key[1:].replace("-", "/")
    return proj_key
