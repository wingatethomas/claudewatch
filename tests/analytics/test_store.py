"""Tests for AnalyticsStore — schema creation, WAL mode, idempotency."""

import os

import pytest
from sqlalchemy.engine import Engine

from claudewatch.backend.analytics.models import AnalyticsStore, Base, SchemaVersionRow


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
        with store.engine.connect() as conn:
            mode = conn.exec_driver_sql("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        store.close()

    def test_foreign_keys_enabled(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        with store.engine.connect() as conn:
            fk = conn.exec_driver_sql("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
        store.close()

    def test_creates_all_tables(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        table_names = set(Base.metadata.tables.keys())
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
        assert expected.issubset(table_names)
        store.close()

    def test_schema_creation_idempotent(self, db_path: str) -> None:
        store1 = AnalyticsStore(db_path)
        store1.close()
        store2 = AnalyticsStore(db_path)
        assert "events" in Base.metadata.tables
        store2.close()

    def test_schema_version_recorded(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        with store.session() as s:
            row = s.query(SchemaVersionRow).first()
            assert row is not None
            assert row.version == 1
        store.close()

    def test_engine_property(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        assert isinstance(store.engine, Engine)
        store.close()

    def test_db_path_property(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        assert store.db_path == db_path
        store.close()

    def test_session_factory(self, db_path: str) -> None:
        store = AnalyticsStore(db_path)
        with store.session() as s:
            assert s is not None
        store.close()
