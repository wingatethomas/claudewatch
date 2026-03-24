"""Static import audit for the claudewatch package.

Parses Python files with the ast module (no execution) to enforce
architectural layer rules, report dependency metrics, and detect
circular dependencies.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from pathlib import Path

# Root of the claudewatch package relative to repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = REPO_ROOT / "claudewatch"
PACKAGE_NAME = "claudewatch"

# ---------------------------------------------------------------------------
# Layer classification
# ---------------------------------------------------------------------------

# Domain directories (siblings of core/ and repositories/ under backend/)
DOMAIN_DIRS = frozenset(
    {
        "detection",
        "summary",
        "notifications",
        "onboarding",
        "updates",
        "usage",
        "activity",
        "bookmark",
        "history",
    }
)

# Minimum part count to identify core sub-packages (e.g. process, session_log)
_MIN_CORE_SUBPACKAGE_PARTS = 3

# Core sub-packages that count as "core/services"
_CORE_SERVICE_PACKAGES = frozenset({"process", "session_log"})


def _classify_backend(parts: list[str]) -> str:
    """Classify a backend module given the parts after 'backend'."""
    if parts[0] == "core":
        if len(parts) >= _MIN_CORE_SUBPACKAGE_PARTS and parts[1] in _CORE_SERVICE_PACKAGES:
            return "core/services"
        return "core"
    if parts[0] == "repositories":
        return "repositories"
    return "domain" if parts[0] in DOMAIN_DIRS else "other"


def _classify(module_path: str) -> str:
    """Return a layer tag for an internal module path.

    Tags:
        "core"           -- backend/core (excluding services)
        "core/services"  -- backend/core/process, backend/core/session_log
        "repositories"   -- backend/repositories
        "domain"         -- any domain package under backend/
        "ui"             -- ui/
        "other"          -- anything else (e.g. __main__)
    """
    parts = module_path.split(".")
    # Strip leading package name
    if parts and parts[0] == PACKAGE_NAME:
        parts = parts[1:]

    if not parts:
        return "other"

    if parts[0] == "ui":
        return "ui"

    if parts[0] == "backend" and len(parts) > 1:
        return _classify_backend(parts[1:])

    return "other"


def _is_config_import(module_path: str) -> bool:
    """Return True if the import targets repositories/config specifically."""
    parts = module_path.split(".")
    if PACKAGE_NAME in parts:
        parts = parts[parts.index(PACKAGE_NAME) + 1 :]
    return parts[:3] == ["backend", "repositories", "config"]


# ---------------------------------------------------------------------------
# Layer rules: (from_layer, to_layer) -> forbidden unless exception applies
# ---------------------------------------------------------------------------

# Pairs that are always forbidden (no exceptions)
_FORBIDDEN_PAIRS: set[tuple[str, str]] = {
    # core/ must not import from domains, repositories, or ui
    ("core", "domain"),
    ("core", "repositories"),
    ("core", "ui"),
    # core/services must not import from domains, repositories, or ui
    ("core/services", "domain"),
    ("core/services", "repositories"),
    ("core/services", "ui"),
    # repositories must not import from domains or ui
    ("repositories", "domain"),
    ("repositories", "ui"),
    # domains must not import from ui
    ("domain", "ui"),
    # ui must not import from repositories (exception handled below)
    ("ui", "repositories"),
}


def _is_violation(from_layer: str, to_layer: str, to_module: str) -> bool:
    """Return True if importing *to_module* from *from_layer* to *to_layer* is a violation."""
    pair = (from_layer, to_layer)
    if pair not in _FORBIDDEN_PAIRS:
        return False
    # Exception: ui may import from repositories/config
    return not (pair == ("ui", "repositories") and _is_config_import(to_module))


# ---------------------------------------------------------------------------
# AST-based import extraction
# ---------------------------------------------------------------------------


def _module_name(filepath: Path) -> str:
    """Convert a file path to a dotted module name relative to the repo root."""
    rel = filepath.relative_to(REPO_ROOT)
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _extract_imports(filepath: Path) -> list[str]:
    """Parse a Python file and return all imported module paths (internal only)."""
    try:
        source = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(PACKAGE_NAME + "."):
                    imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(PACKAGE_NAME + "."):
            imports.append(node.module)
    return imports


# ---------------------------------------------------------------------------
# Dependency graph construction
# ---------------------------------------------------------------------------


def build_graph(package_root: Path) -> dict[str, list[str]]:
    """Return {module: [imported_module, ...]} for all .py files under package_root."""
    graph: dict[str, list[str]] = {}
    for pyfile in sorted(package_root.rglob("*.py")):
        mod = _module_name(pyfile)
        imported = _extract_imports(pyfile)
        if imported:
            graph[mod] = imported
        else:
            graph[mod] = []
    return graph


# ---------------------------------------------------------------------------
# Layer violation checking
# ---------------------------------------------------------------------------


def find_violations(graph: dict[str, list[str]]) -> list[dict[str, str]]:
    """Return a list of dicts describing each layer violation."""
    violations: list[dict[str, str]] = []
    for module, imports in sorted(graph.items()):
        from_layer = _classify(module)
        if from_layer == "other":
            continue
        for imp in imports:
            to_layer = _classify(imp)
            if to_layer == "other":
                continue
            if _is_violation(from_layer, to_layer, imp):
                violations.append(
                    {
                        "module": module,
                        "imports": imp,
                        "from_layer": from_layer,
                        "to_layer": to_layer,
                    }
                )
    return violations


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def compute_fan_out(graph: dict[str, list[str]]) -> dict[str, int]:
    """Fan-out: how many distinct internal modules each module imports."""
    return {mod: len(set(imps)) for mod, imps in graph.items()}


def compute_fan_in(graph: dict[str, list[str]]) -> dict[str, int]:
    """Fan-in: how many modules import each module."""
    fan_in: dict[str, int] = defaultdict(int)
    for imps in graph.values():
        for imp in set(imps):
            fan_in[imp] += 1
    return dict(fan_in)


def find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Detect circular dependencies using DFS. Returns list of cycles."""
    # Normalise graph edges to modules that exist in the graph
    all_modules = set(graph.keys())
    adj: dict[str, set[str]] = {}
    for mod, imps in graph.items():
        adj[mod] = {i for i in set(imps) if i in all_modules}

    visited: set[str] = set()
    on_stack: set[str] = set()
    stack: list[str] = []
    cycles: list[list[str]] = []

    def dfs(node: str) -> None:
        visited.add(node)
        on_stack.add(node)
        stack.append(node)
        for neighbour in sorted(adj.get(node, set())):
            if neighbour not in visited:
                dfs(neighbour)
            elif neighbour in on_stack:
                idx = stack.index(neighbour)
                cycle = stack[idx:] + [neighbour]
                cycles.append(cycle)
        stack.pop()
        on_stack.discard(node)

    for node in sorted(all_modules):
        if node not in visited:
            dfs(node)

    return cycles


def max_import_depth(graph: dict[str, list[str]]) -> int:
    """Compute the longest chain of internal imports (graph diameter via BFS)."""
    all_modules = set(graph.keys())
    adj: dict[str, set[str]] = {}
    for mod, imps in graph.items():
        adj[mod] = {i for i in set(imps) if i in all_modules}

    max_depth = 0
    memo: dict[str, int] = {}

    def depth(node: str, seen: frozenset[str]) -> int:
        if node in memo and not (seen & {node}):
            return memo[node]
        neighbours = adj.get(node, set()) - seen
        if not neighbours:
            return 0
        d = max(1 + depth(n, seen | {node}) for n in neighbours)
        if not seen:
            memo[node] = d
        return d

    for mod in all_modules:
        d = depth(mod, frozenset())
        max_depth = max(max_depth, d)

    return max_depth


# ---------------------------------------------------------------------------
# Output modes
# ---------------------------------------------------------------------------


def print_violations(violations: list[dict[str, str]]) -> None:
    """Print layer violations to stderr."""
    if not violations:
        print("No layer violations found.")
        return
    print(f"Found {len(violations)} layer violation(s):\n", file=sys.stderr)
    for v in violations:
        print(
            f"  VIOLATION: {v['module']} ({v['from_layer']}) -> {v['imports']} ({v['to_layer']})",
            file=sys.stderr,
        )


def print_metrics(graph: dict[str, list[str]]) -> None:
    """Print dependency metrics summary."""
    fan_out = compute_fan_out(graph)
    fan_in = compute_fan_in(graph)
    cycles = find_cycles(graph)
    depth = max_import_depth(graph)

    print("\n--- Dependency Metrics ---\n")

    # Top fan-out
    top_out = sorted(fan_out.items(), key=lambda x: x[1], reverse=True)[:10]
    print("Top 10 fan-out (most imports):")
    for mod, count in top_out:
        if count > 0:
            print(f"  {mod}: {count}")

    # Top fan-in
    print("\nTop 10 fan-in (most imported):")
    top_in = sorted(fan_in.items(), key=lambda x: x[1], reverse=True)[:10]
    for mod, count in top_in:
        print(f"  {mod}: {count}")

    print(f"\nMax import depth: {depth}")

    if cycles:
        print(f"\nCircular dependencies ({len(cycles)}):")
        for cycle in cycles:
            print(f"  {' -> '.join(cycle)}")
    else:
        print("\nNo circular dependencies detected.")


def print_graph_markdown(graph: dict[str, list[str]]) -> None:
    """Print the dependency graph as a markdown table."""
    print("# Dependency Graph\n")
    print("| Module | Imports |")
    print("|--------|---------|")
    for mod in sorted(graph.keys()):
        imps = graph[mod]
        if imps:
            imp_str = ", ".join(f"`{i}`" for i in sorted(set(imps)))
            print(f"| `{mod}` | {imp_str} |")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 on success, 1 if violations found in --check mode."""
    parser = argparse.ArgumentParser(description="Static import audit for claudewatch")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if layer violations found (CI mode)")
    parser.add_argument("--graph", action="store_true", help="Print dependency graph as markdown")
    args = parser.parse_args(argv)

    graph = build_graph(PACKAGE_ROOT)
    violations = find_violations(graph)

    if args.graph:
        print_graph_markdown(graph)
        return 0

    if args.check:
        if violations:
            print_violations(violations)
            return 1
        print("All layer rules OK.")
        return 0

    # Default mode: violations + metrics
    print_violations(violations)
    print_metrics(graph)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
