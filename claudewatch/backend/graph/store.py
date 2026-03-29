"""GraphStore — SQLite-backed persistent storage for the agent relationship graph.

Schema:
  nodes(node_id, kind, label, proj_key, metadata_json, updated_at)
  edges(source, target, kind, created_at)

Designed for fast reads during menu builds and efficient incremental updates
during polling. All writes use UPSERT for idempotency.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from claudewatch.backend.graph.models import EdgeKind, NodeKind

log = logging.getLogger("claudewatch")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id     TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT '',
    proj_key    TEXT NOT NULL DEFAULT '',
    metadata    TEXT NOT NULL DEFAULT '{}',
    updated_at  REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS edges (
    source      TEXT NOT NULL,
    target      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    created_at  REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (source, target, kind),
    FOREIGN KEY (source) REFERENCES nodes(node_id) ON DELETE CASCADE,
    FOREIGN KEY (target) REFERENCES nodes(node_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_proj ON nodes(proj_key);
CREATE INDEX IF NOT EXISTS idx_nodes_proj_kind ON nodes(proj_key, kind);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
"""


class GraphStore:
    """SQLite-backed graph storage with upsert semantics."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._in_batch = False

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Context manager for batching multiple writes in a single transaction."""
        self._in_batch = True
        try:
            yield
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            self._in_batch = False

    def _auto_commit(self) -> None:
        """Commit unless inside a batch context."""
        if not self._in_batch:
            self._conn.commit()

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def upsert_node(
        self,
        node_id: str,
        kind: NodeKind,
        label: str,
        proj_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert or update a node. Metadata is replaced on conflict."""
        meta_json = json.dumps(metadata or {})
        self._conn.execute(
            """
            INSERT INTO nodes (node_id, kind, label, proj_key, metadata, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                kind = excluded.kind,
                label = excluded.label,
                proj_key = excluded.proj_key,
                metadata = excluded.metadata,
                updated_at = excluded.updated_at
            """,
            (node_id, kind.value, label, proj_key, meta_json, time.time()),
        )
        self._auto_commit()

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Get a single node by ID."""
        row = self._conn.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_node(row)

    def get_nodes_by_kind(self, kind: NodeKind) -> list[dict[str, Any]]:
        """Get all nodes of a given kind."""
        rows = self._conn.execute("SELECT * FROM nodes WHERE kind = ?", (kind.value,)).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_nodes_by_project(self, proj_key: str) -> list[dict[str, Any]]:
        """Get all nodes for a project."""
        rows = self._conn.execute("SELECT * FROM nodes WHERE proj_key = ?", (proj_key,)).fetchall()
        return [self._row_to_node(r) for r in rows]

    def delete_node(self, node_id: str) -> None:
        """Delete a node and cascade to its edges."""
        self._conn.execute("DELETE FROM nodes WHERE node_id = ?", (node_id,))
        self._auto_commit()

    def count_nodes(self, proj_key: str, kind: NodeKind) -> int:
        """Count nodes of a kind within a project."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE proj_key = ? AND kind = ?",
            (proj_key, kind.value),
        ).fetchone()
        return row[0] if row else 0

    def get_all_projects(self) -> list[str]:
        """Get all unique project keys."""
        rows = self._conn.execute("SELECT DISTINCT proj_key FROM nodes WHERE proj_key != ''").fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def add_edge(self, source: str, target: str, kind: EdgeKind) -> None:
        """Add an edge. Idempotent via primary key."""
        self._conn.execute(
            """
            INSERT OR IGNORE INTO edges (source, target, kind, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (source, target, kind.value, time.time()),
        )
        self._auto_commit()

    def get_edges_from(self, source: str) -> list[dict[str, Any]]:
        """Get all edges originating from a node."""
        rows = self._conn.execute("SELECT * FROM edges WHERE source = ?", (source,)).fetchall()
        return [self._row_to_edge(r) for r in rows]

    def get_edges_to(self, target: str) -> list[dict[str, Any]]:
        """Get all edges pointing to a node."""
        rows = self._conn.execute("SELECT * FROM edges WHERE target = ?", (target,)).fetchall()
        return [self._row_to_edge(r) for r in rows]

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def get_children(self, node_id: str) -> list[dict[str, Any]]:
        """Get direct child nodes (targets of SPAWNS edges from this node)."""
        rows = self._conn.execute(
            """
            SELECT n.* FROM nodes n
            JOIN edges e ON e.target = n.node_id
            WHERE e.source = ? AND e.kind = ?
            """,
            (node_id, EdgeKind.SPAWNS.value),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_parent(self, node_id: str) -> dict[str, Any] | None:
        """Get the parent node (source of SPAWNS edge to this node)."""
        row = self._conn.execute(
            """
            SELECT n.* FROM nodes n
            JOIN edges e ON e.source = n.node_id
            WHERE e.target = ? AND e.kind = ?
            LIMIT 1
            """,
            (node_id, EdgeKind.SPAWNS.value),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_node(row)

    def get_depth(self, node_id: str) -> int:
        """Get the depth of a node in the spawn tree. Sessions = 0, direct agents = 1, etc."""
        depth = 0
        current = node_id
        while True:
            parent = self.get_parent(current)
            if parent is None:
                break
            depth += 1
            current = parent["node_id"]
        return depth

    def get_subtree(self, node_id: str) -> list[dict[str, Any]]:
        """Get all descendants of a node (recursive BFS)."""
        result: list[dict[str, Any]] = []
        queue: deque[str] = deque([node_id])
        visited: set[str] = {node_id}

        while queue:
            current = queue.popleft()
            children = self.get_children(current)
            for child in children:
                if child["node_id"] not in visited:
                    visited.add(child["node_id"])
                    result.append(child)
                    queue.append(child["node_id"])

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "node_id": row["node_id"],
            "kind": row["kind"],
            "label": row["label"],
            "proj_key": row["proj_key"],
            "metadata": json.loads(row["metadata"]),
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "source": row["source"],
            "target": row["target"],
            "kind": row["kind"],
            "created_at": row["created_at"],
        }

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
