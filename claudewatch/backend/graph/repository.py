"""Graph repository — all database access: session ETL, code ETL, mapper, and queries."""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import sqlite3
import uuid

import kuzu

from claudewatch.backend.core.paths import is_safe_projects_path
from claudewatch.backend.graph.models import (
    ActionStep,
    BehaviorResult,
    FileHistoryResult,
    HotspotResult,
    ImpactResult,
    PRImpactResult,
    ProjectGraphResult,
    RelatedSessionResult,
    WorkflowPattern,
)

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


def _get_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Extract a function's parameter signature."""
    args = node.args
    params = []
    for arg in args.args:
        params.append(arg.arg)
    if args.vararg:
        params.append(f"*{args.vararg.arg}")
    for arg in args.kwonlyargs:
        params.append(arg.arg)
    if args.kwarg:
        params.append(f"**{args.kwarg.arg}")
    return f"({', '.join(params)})"


def _get_call_name(node: ast.Call) -> str:
    """Extract the function name from a call node."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _module_to_file(module: str, project_path: str) -> str:
    """Try to resolve a module name to a file path within the project."""
    parts = module.split(".")
    # Try module.py and module/__init__.py
    rel = os.path.join(*parts) + ".py"
    candidate = os.path.join(project_path, rel)
    if os.path.isfile(candidate):
        return candidate
    pkg = os.path.join(project_path, *parts, "__init__.py")
    if os.path.isfile(pkg):
        return pkg
    return ""


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
        entry: dict[str, object],
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
        block: dict[str, object],
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

    def _process_agent(self, entry: dict[str, object], session_id: str) -> None:
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

    def _update_session_tokens(self, session_id: str, usage: dict[str, int]) -> None:
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

    def _safe_execute(self, query: str, params: dict[str, object] | None = None) -> kuzu.QueryResult | None:
        try:
            return self._conn.execute(query, params or {})
        except RuntimeError:
            log.debug("graph query failed: %s", query[:80])
            return None

    def close(self) -> None:
        self._ckpt.close()


class CodeETL:
    """Parses Python source files into graph nodes via AST analysis."""

    def __init__(self, conn: kuzu.Connection) -> None:
        self._conn = conn

    _MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

    def index_file(self, file_path: str, project_path: str) -> int:
        """Parse a Python file and insert Symbol nodes + edges. Returns symbol count."""
        if not file_path.endswith(".py") or not os.path.isfile(file_path):
            return 0

        try:
            if os.path.getsize(file_path) > self._MAX_FILE_SIZE:
                return 0
            with open(file_path) as f:
                source = f.read()
        except OSError:
            return 0

        file_hash = hashlib.sha256(source.encode()).hexdigest()
        lines = source.count("\n") + 1

        # Check if file already indexed with same hash
        result = self._safe_execute(
            "MATCH (f:File {path: $path}) RETURN f.hash AS hash",
            {"path": file_path},
        )
        if result and result.has_next():
            row = result.get_next()
            if row[0] == file_hash:
                return 0  # already indexed

        # Update file node
        self._safe_execute(
            "MERGE (f:File {path: $path}) "
            "SET f.project = $proj, f.language = 'python', f.hash = $hash, f.lines = $lines",
            {"path": file_path, "proj": project_path, "hash": file_hash, "lines": lines},
        )

        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            log.debug("code etl: syntax error in %s", file_path)
            return 0

        count = 0
        count += self._extract_symbols(tree, file_path)
        self._extract_imports(tree, file_path, project_path)
        return count

    def index_project(self, project_path: str) -> int:
        """Index all Python files in a project directory. Returns total symbols."""
        total = 0
        if not os.path.isdir(project_path):
            return 0
        for root, dirs, files in os.walk(project_path):
            # Skip common non-source directories
            dirs[:] = [
                d
                for d in dirs
                if d
                not in {
                    ".git",
                    ".venv",
                    "venv",
                    "node_modules",
                    "__pycache__",
                    ".tox",
                    ".mypy_cache",
                    ".ruff_cache",
                    "build",
                    "dist",
                }
            ]
            for fname in files:
                if fname.endswith(".py"):
                    fpath = os.path.join(root, fname)
                    total += self.index_file(fpath, project_path)
        return total

    def _extract_symbols(self, tree: ast.Module, file_path: str) -> int:
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                symbol_id = f"{file_path}:{node.name}:{node.lineno}"
                sig = _get_signature(node)
                self._safe_execute(
                    "MERGE (sym:Symbol {id: $id}) "
                    "SET sym.name = $name, sym.qualified_name = $qn, sym.kind = 'function', "
                    "sym.file_path = $fp, sym.start_line = $sl, sym.end_line = $el, "
                    "sym.signature = $sig",
                    {
                        "id": symbol_id,
                        "name": node.name,
                        "qn": f"{file_path}:{node.name}",
                        "fp": file_path,
                        "sl": node.lineno,
                        "el": node.end_lineno or node.lineno,
                        "sig": sig,
                    },
                )
                # DEFINES edge: File → Symbol
                self._safe_execute(
                    "MATCH (f:File {path: $fp}), (sym:Symbol {id: $id}) MERGE (f)-[:DEFINES]->(sym)",
                    {"fp": file_path, "id": symbol_id},
                )
                count += 1

                # Extract calls within this function
                self._extract_calls(node, symbol_id)

            elif isinstance(node, ast.ClassDef):
                symbol_id = f"{file_path}:{node.name}:{node.lineno}"
                self._safe_execute(
                    "MERGE (sym:Symbol {id: $id}) "
                    "SET sym.name = $name, sym.qualified_name = $qn, sym.kind = 'class', "
                    "sym.file_path = $fp, sym.start_line = $sl, sym.end_line = $el, "
                    "sym.signature = ''",
                    {
                        "id": symbol_id,
                        "name": node.name,
                        "qn": f"{file_path}:{node.name}",
                        "fp": file_path,
                        "sl": node.lineno,
                        "el": node.end_lineno or node.lineno,
                    },
                )
                self._safe_execute(
                    "MATCH (f:File {path: $fp}), (sym:Symbol {id: $id}) MERGE (f)-[:DEFINES]->(sym)",
                    {"fp": file_path, "id": symbol_id},
                )
                count += 1

                # CONTAINS edges for methods within this class
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                        method_id = f"{file_path}:{item.name}:{item.lineno}"
                        self._safe_execute(
                            "MATCH (cls:Symbol {id: $cls_id}), (meth:Symbol {id: $meth_id}) "
                            "MERGE (cls)-[:CONTAINS]->(meth)",
                            {"cls_id": symbol_id, "meth_id": method_id},
                        )

        return count

    def _extract_calls(self, func_node: ast.AST, caller_id: str) -> None:
        """Extract function calls within a function body."""
        for node in ast.walk(func_node):
            if not isinstance(node, ast.Call):
                continue
            callee_name = _get_call_name(node)
            if not callee_name:
                continue
            # We can only resolve calls to symbols in the same file
            # Cross-file resolution would require import analysis
            line = getattr(node, "lineno", 0)
            # Create a potential CALLS edge (will only connect if callee exists)
            self._safe_execute(
                "MATCH (caller:Symbol {id: $cid}) "
                "MATCH (callee:Symbol) WHERE callee.name = $name AND callee.file_path = caller.file_path "
                "MERGE (caller)-[:CALLS {line: $line}]->(callee)",
                {"cid": caller_id, "name": callee_name, "line": line},
            )

    def _extract_imports(self, tree: ast.Module, file_path: str, project_path: str) -> None:
        """Extract import statements and create IMPORTS edges between files."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = _module_to_file(alias.name, project_path)
                    if target:
                        self._safe_execute(
                            "MATCH (f1:File {path: $from}), (f2:File {path: $to}) "
                            "MERGE (f1)-[:IMPORTS {name: $name}]->(f2)",
                            {"from": file_path, "to": target, "name": alias.name},
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                target = _module_to_file(node.module, project_path)
                if target:
                    self._safe_execute(
                        "MATCH (f1:File {path: $from}), (f2:File {path: $to}) "
                        "MERGE (f1)-[:IMPORTS {name: $name}]->(f2)",
                        {"from": file_path, "to": target, "name": node.module},
                    )

    def _safe_execute(self, query: str, params: dict[str, object] | None = None) -> kuzu.QueryResult | None:
        try:
            return self._conn.execute(query, params or {})
        except RuntimeError:
            log.debug("code etl query failed: %s", query[:80])
            return None


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


class GraphQueries:
    """All graph read queries via Cypher."""

    def __init__(self, conn: kuzu.Connection) -> None:
        self._conn = conn

    def cascading_impact(self, action_id: str, _depth: int = 3) -> ImpactResult:
        """What are the downstream effects of this edit?"""
        result = self._safe_execute(
            "MATCH (a:Action {kind: 'edit', id: $id})-[:MODIFIES]->(fn:Symbol) "
            "OPTIONAL MATCH (fn)<-[:CALLS*1..3]-(caller:Symbol) "
            "RETURN fn.name AS changed, collect(DISTINCT caller.qualified_name) AS impacted",
            {"id": action_id},
        )
        if not result or not result.has_next():
            return ImpactResult(changed="", impacted=[])
        row = result.get_next()
        return ImpactResult(
            changed=row[0] or "",
            impacted=[x for x in (row[1] or []) if x],
        )

    def intent_chain(self, session_id: str) -> list[ActionStep]:
        """Trace the full action sequence for a session."""
        result = self._safe_execute(
            "MATCH (s:Session {id: $id})-[:PERFORMS]->(a:Action) "
            "RETURN a.kind, a.file_path, a.timestamp "
            "ORDER BY a.timestamp",
            {"id": session_id},
        )
        if not result:
            return []
        steps = []
        while result.has_next():
            row = result.get_next()
            steps.append(
                ActionStep(
                    kind=row[0] or "",
                    file_path=row[1] or "",
                    timestamp=row[2] or "",
                )
            )
        return steps

    def function_hotspots(self, project: str, limit: int = 20) -> list[HotspotResult]:
        """Which functions are being edited most?"""
        result = self._safe_execute(
            "MATCH (a:Action {kind: 'edit'})-[:MODIFIES]->(fn:Symbol) "
            "MATCH (fn)<-[:DEFINES]-(f:File)-[:HAS_FILE]-(p:Project {path: $proj}) "
            "RETURN fn.qualified_name, f.path, count(a) AS edits "
            "ORDER BY edits DESC LIMIT $lim",
            {"proj": project, "lim": limit},
        )
        if not result:
            return []
        hotspots = []
        while result.has_next():
            row = result.get_next()
            hotspots.append(
                HotspotResult(
                    qualified_name=row[0] or "",
                    file_path=row[1] or "",
                    edits=row[2],
                )
            )
        return hotspots

    def related_sessions(self, session_id: str) -> list[RelatedSessionResult]:
        """What other sessions touched the same code?"""
        result = self._safe_execute(
            "MATCH (s1:Session {id: $id})-[:PERFORMS]->(a1:Action)-[:MODIFIES]->(fn:Symbol)"
            "<-[:MODIFIES]-(a2:Action)<-[:PERFORMS]-(s2:Session) "
            "WHERE s1 <> s2 "
            "RETURN s2.id, s2.branch, collect(DISTINCT fn.name) AS shared",
            {"id": session_id},
        )
        if not result:
            return []
        sessions = []
        while result.has_next():
            row = result.get_next()
            sessions.append(
                RelatedSessionResult(
                    session_id=row[0] or "",
                    branch=row[1] or "",
                    shared_symbols=[x for x in (row[2] or []) if x],
                )
            )
        return sessions

    def agent_behavior(self, agent_type: str) -> list[BehaviorResult]:
        """How do different agent types use tools?"""
        result = self._safe_execute(
            "MATCH (s:Session)-[:SPAWNS]->(ag:Agent {agent_type: $type}) "
            "MATCH (s)-[:PERFORMS]->(a:Action) "
            "RETURN a.kind, count(*) AS frequency ORDER BY frequency DESC",
            {"type": agent_type},
        )
        if not result:
            return []
        behaviors = []
        while result.has_next():
            row = result.get_next()
            behaviors.append(BehaviorResult(kind=row[0] or "", frequency=row[1]))
        return behaviors

    def project_graph(self, project: str) -> ProjectGraphResult:
        """Counts of graph entities for a project."""
        files = self._count(
            "MATCH (p:Project {path: $proj})-[:HAS_FILE]->(f:File) RETURN count(f)",
            {"proj": project},
        )
        symbols = self._count(
            "MATCH (p:Project {path: $proj})-[:HAS_FILE]->(f:File)-[:DEFINES]->(s:Symbol) RETURN count(s)",
            {"proj": project},
        )
        sessions = self._count(
            "MATCH (s:Session)-[:IN_PROJECT]->(p:Project {path: $proj}) RETURN count(s)",
            {"proj": project},
        )
        actions = self._count(
            "MATCH (s:Session)-[:IN_PROJECT]->(p:Project {path: $proj}), (s)-[:PERFORMS]->(a:Action) RETURN count(a)",
            {"proj": project},
        )
        return ProjectGraphResult(files=files, symbols=symbols, sessions=sessions, actions=actions)

    def project_graph_all(self) -> ProjectGraphResult:
        """Global counts across all projects."""
        files = self._count("MATCH (f:File) RETURN count(f)", {})
        symbols = self._count("MATCH (s:Symbol) RETURN count(s)", {})
        sessions = self._count("MATCH (s:Session) RETURN count(s)", {})
        actions = self._count("MATCH (a:Action) RETURN count(a)", {})
        return ProjectGraphResult(files=files, symbols=symbols, sessions=sessions, actions=actions)

    def workflow_patterns_all(self, limit: int = 10) -> list[WorkflowPattern]:
        """Global workflow patterns across all projects."""
        result = self._safe_execute(
            "MATCH (a1:Action)-[:NEXT]->(a2:Action) "
            "RETURN a1.kind AS first, a2.kind AS then, count(*) AS frequency "
            "ORDER BY frequency DESC LIMIT $lim",
            {"lim": limit},
        )
        if not result:
            return []
        patterns = []
        while result.has_next():
            row = result.get_next()
            patterns.append(WorkflowPattern(first=row[0] or "", then=row[1] or "", frequency=row[2]))
        return patterns

    def force_graph_data(self, limit: int = 200) -> dict[str, list[dict[str, str]]]:
        """Get nodes and edges for force-directed graph visualization."""
        result = self._safe_execute(
            "MATCH (s:Session)-[:PERFORMS]->(a:Action) "
            "OPTIONAL MATCH (a)-[:TARGETS]->(f:File) "
            "RETURN s.id, a.id, a.kind, a.timestamp, f.path "
            "ORDER BY a.timestamp DESC LIMIT $lim",
            {"lim": limit},
        )
        nodes: dict[str, dict[str, str]] = {}
        edges: list[dict[str, str]] = []
        if not result:
            return {"nodes": [], "edges": []}
        while result.has_next():
            row = result.get_next()
            sid, aid, akind, ats, fpath = row
            if sid and sid not in nodes:
                nodes[sid] = {"id": sid, "type": "session", "label": sid[:8]}
            if aid and aid not in nodes:
                nodes[aid] = {"id": aid, "type": "action", "label": akind or "action"}
            if fpath and fpath not in nodes:
                short = fpath.rsplit("/", 1)[-1] if "/" in fpath else fpath
                nodes[fpath] = {"id": fpath, "type": "file", "label": short}
            if sid and aid:
                edges.append({"source": sid, "target": aid, "type": "performs"})
            if aid and fpath:
                edges.append({"source": aid, "target": fpath, "type": "targets"})
        return {"nodes": list(nodes.values()), "edges": edges}

    def pr_blast_radius(self, pr_number: int) -> PRImpactResult:
        """What does this PR actually touch?"""
        result = self._safe_execute(
            "MATCH (s:Session)-[:REFERENCES]->(pr:PR {number: $num}) "
            "MATCH (s)-[:PERFORMS]->(a:Action {kind: 'edit'})-[:MODIFIES]->(fn:Symbol) "
            "OPTIONAL MATCH (fn)<-[:CALLS*0..2]-(dep:Symbol) "
            "RETURN fn.name AS changed, collect(DISTINCT dep.qualified_name) AS deps",
            {"num": pr_number},
        )
        if not result:
            return PRImpactResult()
        changed = []
        dependents = set()
        while result.has_next():
            row = result.get_next()
            if row[0]:
                changed.append(row[0])
            for d in row[1] or []:
                if d:
                    dependents.add(d)
        return PRImpactResult(changed=changed, dependents=list(dependents))

    def workflow_patterns(self, project: str, limit: int = 10) -> list[WorkflowPattern]:
        """What's the typical action sequence?"""
        result = self._safe_execute(
            "MATCH (a1:Action)-[:NEXT]->(a2:Action) "
            "MATCH (s:Session)-[:PERFORMS]->(a1) "
            "MATCH (s)-[:IN_PROJECT]->(p:Project {path: $proj}) "
            "RETURN a1.kind AS first, a2.kind AS then, count(*) AS frequency "
            "ORDER BY frequency DESC LIMIT $lim",
            {"proj": project, "lim": limit},
        )
        if not result:
            return []
        patterns = []
        while result.has_next():
            row = result.get_next()
            patterns.append(
                WorkflowPattern(
                    first=row[0] or "",
                    then=row[1] or "",
                    frequency=row[2],
                )
            )
        return patterns

    def file_history(self, file_path: str) -> list[FileHistoryResult]:
        """All actions targeting a specific file."""
        result = self._safe_execute(
            "MATCH (a:Action)-[:TARGETS]->(f:File {path: $fp}) "
            "MATCH (s:Session)-[:PERFORMS]->(a) "
            "RETURN s.id, a.kind, a.timestamp ORDER BY a.timestamp",
            {"fp": file_path},
        )
        if not result:
            return []
        history = []
        while result.has_next():
            row = result.get_next()
            history.append(
                FileHistoryResult(
                    session_id=row[0] or "",
                    action_kind=row[1] or "",
                    timestamp=row[2] or "",
                )
            )
        return history

    def sessions_for_symbol(self, symbol_name: str) -> list[str]:
        """Which sessions modified a given symbol?"""
        result = self._safe_execute(
            "MATCH (s:Session)-[:PERFORMS]->(a:Action)-[:MODIFIES]->(sym:Symbol {name: $name}) RETURN DISTINCT s.id",
            {"name": symbol_name},
        )
        if not result:
            return []
        sessions = []
        while result.has_next():
            sessions.append(result.get_next()[0])
        return sessions

    def recent_edits_with_symbols(self, limit: int = 20) -> list[dict[str, str]]:
        """Recent edit actions linked to the functions they modified."""
        result = self._safe_execute(
            "MATCH (a:Action {kind: 'edit'})-[:MODIFIES]->(sym:Symbol) "
            "RETURN a.file_path, sym.name, sym.qualified_name, a.timestamp, a.session_id "
            "ORDER BY a.timestamp DESC LIMIT $lim",
            {"lim": limit},
        )
        if not result:
            return []
        edits = []
        while result.has_next():
            row = result.get_next()
            edits.append(
                {
                    "file_path": row[0] or "",
                    "function": row[1] or "",
                    "qualified_name": row[2] or "",
                    "timestamp": row[3] or "",
                    "session_id": row[4] or "",
                }
            )
        return edits

    def active_project_paths(self) -> list[str]:
        """Get distinct project paths from the graph."""
        result = self._safe_execute("MATCH (p:Project) RETURN p.path", {})
        if not result:
            return []
        paths = []
        while result.has_next():
            path = result.get_next()[0]
            if path:
                paths.append(path)
        return paths

    def _count(self, query: str, params: dict[str, object]) -> int:
        result = self._safe_execute(query, params)
        if not result or not result.has_next():
            return 0
        return result.get_next()[0] or 0

    def _safe_execute(self, query: str, params: dict[str, object] | None = None) -> kuzu.QueryResult | None:
        try:
            return self._conn.execute(query, params or {})
        except RuntimeError:
            log.debug("graph query failed: %s", query[:80])
            return None
