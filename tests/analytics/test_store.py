"""Tests for AnalyticsStore — schema creation, WAL mode, idempotency."""

import os
import sqlite3

import pytest

from claudewatch.backend.analytics.store import AnalyticsStore


@pytest.fixture
def db_path(tmp_path: str) -> str:
    return os.path.join(tmp_path, "test_analytics.db")


class TestAnalyticsStore:
    def test_creates_database(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        assert os.path.exists(db_path)
        store.close()

    def test_wal_mode_enabled(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        store.close()

    def test_foreign_keys_enabled(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        fk = store.conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
        store.close()

    def test_creates_all_tables(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        tables = {r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        expected = {
            "events",
            "tools",
            "files",
            "tokens",
            "pull_requests",
            "agents",
            "sessions",
            "checkpoints",
            "schema_version",
        }
        assert expected.issubset(tables)
        store.close()

    def test_schema_creation_idempotent(self, db_path: str) -> None:
        store1 = AnalyticsStore(db_path)
        store1.close()
        store2 = AnalyticsStore(db_path)
        tables = {r[0] for r in store2.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "events" in tables
        store2.close()

    def test_schema_version_recorded(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        row = store.conn.execute("SELECT version FROM schema_version").fetchone()
        assert row[0] == 1
        store.close()

    def test_conn_property(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        assert isinstance(store.conn, sqlite3.Connection)
        store.close()

    def test_db_path_property(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        assert store.db_path == db_path
        store.close()

    def test_row_factory_set(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        assert store.conn.row_factory == sqlite3.Row
        store.close()

    def test_indexes_created(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        indexes = {
            r[0]
            for r in store.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchall()
        }
        assert "idx_events_proj_ts" in indexes
        assert "idx_tools_proj_name" in indexes
        assert "idx_files_session" in indexes
        store.close()
