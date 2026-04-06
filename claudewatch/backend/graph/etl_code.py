"""ETL pipeline 2: AST parsing → File, Symbol, Import, Call nodes and edges."""

from __future__ import annotations

import ast
import hashlib
import logging
import os

import kuzu

log = logging.getLogger("claudewatch")


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
