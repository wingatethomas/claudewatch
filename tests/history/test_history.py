"""Tests for claudewatch.backend.repositories.history."""

import json
import os
from unittest.mock import patch

from claudewatch.backend.history import repository as history


class TestRecordSession:
    """Tests for record_session."""

    def test_records_new_session(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with patch.object(history, "_PATH", fake_path):
            history.record_session("sess-1", "myproject", "/tmp/myproject", "claude-opus-4-6", "Terminal")
            entries = history._load()

        assert len(entries) == 1
        assert entries[0]["session_id"] == "sess-1"
        assert entries[0]["project"] == "myproject"
        assert entries[0]["cwd"] == "/tmp/myproject"
        assert entries[0]["model"] == "claude-opus-4-6"
        assert entries[0]["host_app"] == "Terminal"
        assert "ended_at" in entries[0]

    def test_deduplicates_by_cwd(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with patch.object(history, "_PATH", fake_path):
            history.record_session("sess-1", "proj", "/cwd", "opus", "Terminal")
            history.record_session("sess-2", "proj", "/cwd", "sonnet", "Terminal")
            entries = history._load()

        assert len(entries) == 1
        assert entries[0]["session_id"] == "sess-2"
        assert entries[0]["model"] == "sonnet"

    def test_different_cwds_kept(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with patch.object(history, "_PATH", fake_path):
            history.record_session("sess-1", "proj-a", "/a", "", "Terminal")
            history.record_session("sess-2", "proj-b", "/b", "", "Terminal")
            entries = history._load()

        assert len(entries) == 2

    def test_caps_at_max_entries(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with patch.object(history, "_PATH", fake_path), patch.object(history, "_MAX_ENTRIES", 3):
            for i in range(5):
                history.record_session(f"sess-{i}", f"proj-{i}", f"/cwd-{i}", "", "Terminal")
            entries = history._load()

        assert len(entries) == 3
        assert entries[-1]["session_id"] == "sess-4"


class TestGetHistory:
    """Tests for get_history."""

    def test_returns_newest_first(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with patch.object(history, "_PATH", fake_path):
            history.record_session("sess-1", "proj-a", "/a", "", "Terminal")
            history.record_session("sess-2", "proj-b", "/b", "", "Terminal")
            result = history.get_history()

        assert result[0].session_id == "sess-2"
        assert result[1].session_id == "sess-1"

    def test_seeds_from_jsonl_when_empty(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        proj_dir = tmp_path / "projects" / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n")

        with (
            patch.object(history, "_PATH", fake_path),
            patch("claudewatch.backend.history.repository.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(tmp_path / "projects")),
        ):
            result = history.get_history()

        assert len(result) >= 1
        assert result[0].project == "myapp"


class TestSeedFromJsonl:
    """Tests for _seed_from_jsonl."""

    def test_no_projects_dir_returns_empty(self, tmp_path):
        with patch("claudewatch.backend.history.repository.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")):
            result = history._seed_from_jsonl()
        assert result == []

    def test_skips_non_directory_entries(self, tmp_path):
        proj_base = tmp_path / "projects"
        proj_base.mkdir()
        (proj_base / "a-file.txt").write_text("not a dir")

        fake_path = str(tmp_path / "history.json")
        with (
            patch.object(history, "_PATH", fake_path),
            patch("claudewatch.backend.history.repository.CLAUDE_PROJECTS_DIR", str(proj_base)),
        ):
            result = history._seed_from_jsonl()
        assert result == []

    def test_reconstructs_cwd_from_proj_key(self, tmp_path):
        proj_base = tmp_path / "projects"
        proj_dir = proj_base / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "abc123.jsonl"
        jsonl.write_text("{}\n")

        fake_path = str(tmp_path / "history.json")
        with (
            patch.object(history, "_PATH", fake_path),
            patch("claudewatch.backend.history.repository.CLAUDE_PROJECTS_DIR", str(proj_base)),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(proj_base)),
        ):
            result = history._seed_from_jsonl()

        assert len(result) == 1
        assert result[0]["cwd"] == "/Users/dev/myapp"
        assert result[0]["project"] == "myapp"
        assert result[0]["session_id"] == "abc123"

    def test_extracts_model_from_jsonl_tail(self, tmp_path):
        proj_base = tmp_path / "projects"
        proj_dir = proj_base / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n")

        fake_path = str(tmp_path / "history.json")
        with (
            patch.object(history, "_PATH", fake_path),
            patch("claudewatch.backend.history.repository.CLAUDE_PROJECTS_DIR", str(proj_base)),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(proj_base)),
        ):
            result = history._seed_from_jsonl()

        assert result[0]["model"] == "claude-opus-4-6"

    def test_uses_most_recent_jsonl(self, tmp_path):
        proj_base = tmp_path / "projects"
        proj_dir = proj_base / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)

        old = proj_dir / "old.jsonl"
        old.write_text("{}\n")
        os.utime(old, (1000, 1000))

        new = proj_dir / "new.jsonl"
        new.write_text("{}\n")
        os.utime(new, (2000, 2000))

        fake_path = str(tmp_path / "history.json")
        with (
            patch.object(history, "_PATH", fake_path),
            patch("claudewatch.backend.history.repository.CLAUDE_PROJECTS_DIR", str(proj_base)),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(proj_base)),
        ):
            result = history._seed_from_jsonl()

        assert result[0]["session_id"] == "new"

    def test_saves_seeded_entries_to_disk(self, tmp_path):
        proj_base = tmp_path / "projects"
        proj_dir = proj_base / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        (proj_dir / "s.jsonl").write_text("{}\n")

        fake_path = str(tmp_path / "history.json")
        with (
            patch.object(history, "_PATH", fake_path),
            patch("claudewatch.backend.history.repository.CLAUDE_PROJECTS_DIR", str(proj_base)),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(proj_base)),
        ):
            history._seed_from_jsonl()

        with open(fake_path) as f:
            data = json.load(f)
        assert len(data) >= 1


class TestRemoveHistoryEntry:
    """Tests for remove_history_entry."""

    def test_removes_matching_entry(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with patch.object(history, "_PATH", fake_path):
            history.record_session("s1", "p1", "/a", "", "Terminal")
            history.record_session("s2", "p2", "/b", "", "Terminal")
            history.remove_history_entry("/a")
            entries = history._load()

        assert len(entries) == 1
        assert entries[0]["cwd"] == "/b"

    def test_remove_nonexistent_is_noop(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with patch.object(history, "_PATH", fake_path):
            history.record_session("s1", "p1", "/a", "", "Terminal")
            history.remove_history_entry("/nonexistent")
            entries = history._load()

        assert len(entries) == 1


class TestLoadEdgeCases:
    """Edge cases for _load."""

    def test_nonexistent_file_returns_empty(self, tmp_path):
        fake_path = str(tmp_path / "nope.json")
        with patch.object(history, "_PATH", fake_path):
            result = history._load()
        assert result == []

    def test_corrupt_json_returns_empty(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with open(fake_path, "w") as f:
            f.write("{corrupt")
        with patch.object(history, "_PATH", fake_path):
            result = history._load()
        assert result == []

    def test_non_list_json_returns_empty(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with open(fake_path, "w") as f:
            json.dump({"not": "a list"}, f)
        with patch.object(history, "_PATH", fake_path):
            result = history._load()
        assert result == []

    def test_prunes_to_max_entries(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        data = [{"cwd": f"/c{i}", "session_id": f"s{i}"} for i in range(60)]
        with open(fake_path, "w") as f:
            json.dump(data, f)

        with patch.object(history, "_PATH", fake_path):
            result = history._load()

        assert len(result) == 50


class TestModelNormalization:
    """_load migrates stale display-name model values back to raw ids."""

    def test_old_short_display_name_normalized(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with open(fake_path, "w") as f:
            json.dump([{"cwd": "/a", "session_id": "s1", "model": "o4.6"}], f)

        with patch.object(history, "_PATH", fake_path):
            result = history._load()

        assert result[0]["model"] == "claude-opus-4-6"

    def test_new_long_display_name_normalized(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with open(fake_path, "w") as f:
            json.dump([{"cwd": "/a", "session_id": "s1", "model": "opus 4.6"}], f)

        with patch.object(history, "_PATH", fake_path):
            result = history._load()

        assert result[0]["model"] == "claude-opus-4-6"

    def test_synthetic_placeholder_cleared(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with open(fake_path, "w") as f:
            json.dump([{"cwd": "/a", "session_id": "s1", "model": "<synthetic>"}], f)

        with patch.object(history, "_PATH", fake_path):
            result = history._load()

        assert result[0]["model"] == ""

    def test_raw_id_untouched(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with open(fake_path, "w") as f:
            json.dump([{"cwd": "/a", "session_id": "s1", "model": "claude-opus-4-7"}], f)

        with patch.object(history, "_PATH", fake_path):
            result = history._load()

        assert result[0]["model"] == "claude-opus-4-7"

    def test_normalization_persisted(self, tmp_path):
        # Stale values should be rewritten back to disk so future reads are clean.
        fake_path = str(tmp_path / "history.json")
        with open(fake_path, "w") as f:
            json.dump([{"cwd": "/a", "session_id": "s1", "model": "o4.6"}], f)

        with patch.object(history, "_PATH", fake_path):
            history._load()

        with open(fake_path) as f:
            on_disk = json.load(f)
        assert on_disk[0]["model"] == "claude-opus-4-6"


class TestNoReseedOnEmpty:
    """get_history must NOT reseed if the file exists but the list is empty."""

    def test_no_reseed_when_file_exists_empty(self, tmp_path):
        fake_path = str(tmp_path / "history.json")
        with open(fake_path, "w") as f:
            json.dump([], f)  # user cleared their history

        proj_base = tmp_path / "projects"
        proj_dir = proj_base / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        (proj_dir / "session.jsonl").write_text("{}\n")

        with (
            patch.object(history, "_PATH", fake_path),
            patch("claudewatch.backend.history.repository.CLAUDE_PROJECTS_DIR", str(proj_base)),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(proj_base)),
        ):
            result = history.get_history()

        assert result == []

    def test_seeds_when_file_missing(self, tmp_path):
        # Inverse: first-ever launch should still seed from JSONL.
        fake_path = str(tmp_path / "history.json")
        proj_base = tmp_path / "projects"
        proj_dir = proj_base / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        with open(proj_dir / "session.jsonl", "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n")

        with (
            patch.object(history, "_PATH", fake_path),
            patch("claudewatch.backend.history.repository.CLAUDE_PROJECTS_DIR", str(proj_base)),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(proj_base)),
        ):
            result = history.get_history()

        assert len(result) >= 1


class TestSeedFiltersSynthetic:
    """_seed_from_jsonl must not store '<synthetic>' as a model value."""

    def test_synthetic_in_tail_treated_as_empty(self, tmp_path):
        proj_base = tmp_path / "projects"
        proj_dir = proj_base / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "<synthetic>"}}) + "\n")

        fake_path = str(tmp_path / "history.json")
        with (
            patch.object(history, "_PATH", fake_path),
            patch("claudewatch.backend.history.repository.CLAUDE_PROJECTS_DIR", str(proj_base)),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(proj_base)),
        ):
            result = history._seed_from_jsonl()

        assert result[0]["model"] == ""

    def test_real_model_preferred_over_synthetic(self, tmp_path):
        proj_base = tmp_path / "projects"
        proj_dir = proj_base / "-Users-dev-myapp"
        proj_dir.mkdir(parents=True)
        jsonl = proj_dir / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-6"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"model": "<synthetic>"}}) + "\n")

        fake_path = str(tmp_path / "history.json")
        with (
            patch.object(history, "_PATH", fake_path),
            patch("claudewatch.backend.history.repository.CLAUDE_PROJECTS_DIR", str(proj_base)),
            patch("claudewatch.backend.core.session_log.jsonl.CLAUDE_PROJECTS_DIR", str(proj_base)),
        ):
            result = history._seed_from_jsonl()

        assert result[0]["model"] == "claude-opus-4-6"
