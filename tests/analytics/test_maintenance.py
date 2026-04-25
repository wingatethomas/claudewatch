"""Tests for Maintenance — analytics retention sweep."""

import os
import time

import pytest

from claudewatch.backend.analytics.models import (
    AgentRow,
    AnalyticsStore,
    EventRow,
    FileRow,
    PullRequestRow,
    SessionRow,
    TokenRow,
    ToolRow,
)
from claudewatch.backend.analytics.repository import Maintenance


@pytest.fixture
def store(tmp_path: str) -> AnalyticsStore:
    return AnalyticsStore(os.path.join(tmp_path, "test.db"))


@pytest.fixture
def maintenance(store: AnalyticsStore) -> Maintenance:
    return Maintenance(store.session)


def _seed_event(store: AnalyticsStore, *, ts_epoch: float, session_id: str = "s1") -> None:
    with store.session() as s:
        s.add(
            EventRow(
                session_id=session_id,
                uuid=f"e-{ts_epoch}",
                entry_type="user",
                timestamp="x",
                ts_epoch=ts_epoch,
                proj_key="pk",
            )
        )
        s.commit()


def _seed_session(store: AnalyticsStore, *, session_id: str, last_epoch: float | None) -> None:
    with store.session() as s:
        s.add(SessionRow(session_id=session_id, proj_key="pk", last_epoch=last_epoch))
        s.commit()


def _seed_agent(store: AnalyticsStore, *, agent_id: str, session_id: str) -> None:
    with store.session() as s:
        s.add(
            AgentRow(
                agent_id=agent_id,
                session_id=session_id,
                agent_type="t",
                description="",
                proj_key="pk",
            )
        )
        s.commit()


class TestMaintenance:
    def test_prunes_old_event_rows(self, store: AnalyticsStore, maintenance: Maintenance) -> None:
        now = time.time()
        _seed_event(store, ts_epoch=now - 365 * 86400)  # 1 year old
        _seed_event(store, ts_epoch=now - 1 * 86400)  # 1 day old
        deleted = maintenance.prune_older_than(now - 180 * 86400)
        assert deleted.get("events") == 1
        with store.session() as s:
            assert s.query(EventRow).count() == 1

    def test_prunes_across_all_time_series_tables(
        self, store: AnalyticsStore, maintenance: Maintenance
    ) -> None:
        now = time.time()
        old = now - 365 * 86400
        with store.session() as s:
            s.add(EventRow(session_id="s", entry_type="t", timestamp="x", ts_epoch=old, proj_key="pk"))
            s.add(ToolRow(session_id="s", name="Bash", timestamp="x", ts_epoch=old, proj_key="pk"))
            s.add(FileRow(session_id="s", path="/p", access_type="read", timestamp="x", ts_epoch=old, proj_key="pk"))
            s.add(TokenRow(session_id="s", model="m", timestamp="x", ts_epoch=old, proj_key="pk"))
            s.add(
                PullRequestRow(
                    session_id="s", number=1, url="u", repository="r", timestamp="x", ts_epoch=old, proj_key="pk"
                )
            )
            s.commit()
        deleted = maintenance.prune_older_than(now - 180 * 86400)
        assert deleted == {
            "events": 1,
            "tools": 1,
            "files": 1,
            "tokens": 1,
            "pull_requests": 1,
        }

    def test_keeps_recent_rows(self, store: AnalyticsStore, maintenance: Maintenance) -> None:
        now = time.time()
        _seed_event(store, ts_epoch=now - 1 * 86400)
        deleted = maintenance.prune_older_than(now - 180 * 86400)
        assert "events" not in deleted
        with store.session() as s:
            assert s.query(EventRow).count() == 1

    def test_prunes_old_sessions_by_last_epoch(
        self, store: AnalyticsStore, maintenance: Maintenance
    ) -> None:
        now = time.time()
        _seed_session(store, session_id="old", last_epoch=now - 365 * 86400)
        _seed_session(store, session_id="recent", last_epoch=now - 1 * 86400)
        deleted = maintenance.prune_older_than(now - 180 * 86400)
        assert deleted.get("sessions") == 1
        with store.session() as s:
            remaining = {row.session_id for row in s.query(SessionRow).all()}
        assert remaining == {"recent"}

    def test_keeps_sessions_with_null_last_epoch(
        self, store: AnalyticsStore, maintenance: Maintenance
    ) -> None:
        _seed_session(store, session_id="never_active", last_epoch=None)
        maintenance.prune_older_than(time.time() - 180 * 86400)
        with store.session() as s:
            assert s.query(SessionRow).count() == 1

    def test_prunes_orphan_agents(self, store: AnalyticsStore, maintenance: Maintenance) -> None:
        now = time.time()
        _seed_session(store, session_id="alive", last_epoch=now - 1 * 86400)
        _seed_agent(store, agent_id="a-alive", session_id="alive")
        _seed_agent(store, agent_id="a-orphan", session_id="dead")  # session never seeded
        deleted = maintenance.prune_older_than(now - 180 * 86400)
        assert deleted.get("agents") == 1
        with store.session() as s:
            remaining = {row.agent_id for row in s.query(AgentRow).all()}
        assert remaining == {"a-alive"}

    def test_returns_empty_dict_when_nothing_to_prune(
        self, store: AnalyticsStore, maintenance: Maintenance
    ) -> None:
        deleted = maintenance.prune_older_than(time.time() - 180 * 86400)
        assert deleted == {}

    def test_idempotent_when_called_twice(self, store: AnalyticsStore, maintenance: Maintenance) -> None:
        now = time.time()
        _seed_event(store, ts_epoch=now - 365 * 86400)
        first = maintenance.prune_older_than(now - 180 * 86400)
        second = maintenance.prune_older_than(now - 180 * 86400)
        assert first.get("events") == 1
        assert "events" not in second
