"""Tests for GraphStore — Kuzu schema creation and connection management."""

import os

import kuzu
import pytest

from claudewatch.backend.graph.store import GraphStore


@pytest.fixture
def db_path(tmp_path: str) -> str:
    return os.path.join(tmp_path, "test_graph.kuzu")


class TestGraphStore:
    def test_creates_database(self, db_path: str) -> None:
        store = GraphStore(db_path)
        assert os.path.exists(db_path)
        store.close()

    def test_conn_is_kuzu_connection(self, db_path: str) -> None:
        store = GraphStore(db_path)
        assert isinstance(store.conn, kuzu.Connection)
        store.close()

    def test_node_tables_created(self, db_path: str) -> None:
        store = GraphStore(db_path)
        for table in ["Project", "File", "Symbol", "Session", "Agent", "Action", "PR"]:
            result = store.conn.execute(f"MATCH (n:{table}) RETURN count(n)")  # noqa: S608
            assert result.has_next()
        store.close()

    def test_rel_tables_created(self, db_path: str) -> None:
        store = GraphStore(db_path)
        store.conn.execute("CREATE (p:Project {path: '/test', name: 'test'})")
        store.conn.execute(
            "CREATE (f:File {path: '/test/main.py', project: '/test', language: 'python', hash: '', lines: 10})"
        )
        store.conn.execute(
            "MATCH (p:Project {path: '/test'}), (f:File {path: '/test/main.py'}) CREATE (p)-[:HAS_FILE]->(f)"
        )
        result = store.conn.execute("MATCH (p:Project)-[:HAS_FILE]->(f:File) RETURN f.path")
        assert result.has_next()
        store.close()

    def test_schema_idempotent(self, db_path: str) -> None:
        store1 = GraphStore(db_path)
        store1.close()
        store2 = GraphStore(db_path)
        result = store2.conn.execute("MATCH (n:Project) RETURN count(n)")
        assert result.has_next()
        store2.close()

    def test_db_path_property(self, db_path: str) -> None:
        store = GraphStore(db_path)
        assert store.db_path == db_path
        store.close()
