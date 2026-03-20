"""Tests for claudewatch.backend.repositories.bookmarks."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from claudewatch.backend.repositories import bookmarks


class TestBookmarkSaveAndGetAll:
    """Saving and retrieving bookmarks."""

    def test_save_and_get_all(self, tmp_path):
        fake_path = str(tmp_path / "sessions.json")
        with patch.object(bookmarks, "_PATH", fake_path):
            bookmarks.save_bookmark("abc-123", "myproject", "/tmp/myproject", "working on auth")
            result = bookmarks.get_bookmarks()

        assert len(result) == 1
        assert result[0]["session_id"] == "abc-123"
        assert result[0]["project"] == "myproject"
        assert result[0]["cwd"] == "/tmp/myproject"
        assert result[0]["note"] == "working on auth"
        assert "timestamp" in result[0]

    def test_save_multiple(self, tmp_path):
        fake_path = str(tmp_path / "sessions.json")
        with patch.object(bookmarks, "_PATH", fake_path):
            bookmarks.save_bookmark("id-1", "proj-a", "/a", "note a")
            bookmarks.save_bookmark("id-2", "proj-b", "/b", "note b")
            result = bookmarks.get_bookmarks()

        assert len(result) == 2
        assert result[0]["session_id"] == "id-1"
        assert result[1]["session_id"] == "id-2"

    def test_save_persists_to_disk(self, tmp_path):
        fake_path = str(tmp_path / "sessions.json")
        with patch.object(bookmarks, "_PATH", fake_path):
            bookmarks.save_bookmark("abc-123", "myproject", "/tmp/myproject", "note")

        with open(fake_path) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["session_id"] == "abc-123"


class TestBookmarkUpdateExisting:
    """Re-saving the same session_id updates it in place."""

    def test_update_note_and_timestamp(self, tmp_path):
        fake_path = str(tmp_path / "sessions.json")
        with patch.object(bookmarks, "_PATH", fake_path):
            bookmarks.save_bookmark("abc-123", "proj", "/cwd", "old note")
            old_ts = bookmarks.get_bookmarks()[0]["timestamp"]

            bookmarks.save_bookmark("abc-123", "proj", "/cwd", "new note")
            result = bookmarks.get_bookmarks()

        assert len(result) == 1
        assert result[0]["note"] == "new note"
        assert result[0]["timestamp"] >= old_ts

    def test_update_does_not_duplicate(self, tmp_path):
        fake_path = str(tmp_path / "sessions.json")
        with patch.object(bookmarks, "_PATH", fake_path):
            bookmarks.save_bookmark("abc-123", "proj", "/cwd", "first")
            bookmarks.save_bookmark("abc-123", "proj", "/cwd", "second")
            bookmarks.save_bookmark("abc-123", "proj", "/cwd", "third")
            result = bookmarks.get_bookmarks()

        assert len(result) == 1
        assert result[0]["note"] == "third"


class TestBookmarkRemove:
    """Removing bookmarks by session_id."""

    def test_remove_existing(self, tmp_path):
        fake_path = str(tmp_path / "sessions.json")
        with patch.object(bookmarks, "_PATH", fake_path):
            bookmarks.save_bookmark("id-1", "proj-a", "/a", "note a")
            bookmarks.save_bookmark("id-2", "proj-b", "/b", "note b")
            bookmarks.remove_bookmark("id-1")
            result = bookmarks.get_bookmarks()

        assert len(result) == 1
        assert result[0]["session_id"] == "id-2"

    def test_remove_nonexistent_is_noop(self, tmp_path):
        fake_path = str(tmp_path / "sessions.json")
        with patch.object(bookmarks, "_PATH", fake_path):
            bookmarks.save_bookmark("id-1", "proj-a", "/a", "note a")
            bookmarks.remove_bookmark("id-nonexistent")
            result = bookmarks.get_bookmarks()

        assert len(result) == 1

    def test_remove_all(self, tmp_path):
        fake_path = str(tmp_path / "sessions.json")
        with patch.object(bookmarks, "_PATH", fake_path):
            bookmarks.save_bookmark("id-1", "proj-a", "/a", "note a")
            bookmarks.remove_bookmark("id-1")
            result = bookmarks.get_bookmarks()

        assert len(result) == 0


class TestBookmarkTTLPruning:
    """Entries older than _TTL_DAYS are pruned on load."""

    def test_old_entries_pruned(self, tmp_path):
        fake_path = str(tmp_path / "sessions.json")
        old_ts = (datetime.now(tz=UTC) - timedelta(days=31)).isoformat()
        recent_ts = datetime.now(tz=UTC).isoformat()

        data = [
            {"session_id": "old", "project": "p", "cwd": "/", "note": "n", "timestamp": old_ts},
            {"session_id": "new", "project": "p", "cwd": "/", "note": "n", "timestamp": recent_ts},
        ]
        with open(fake_path, "w") as f:
            json.dump(data, f)

        with patch.object(bookmarks, "_PATH", fake_path):
            result = bookmarks.get_bookmarks()

        assert len(result) == 1
        assert result[0]["session_id"] == "new"

    def test_pruning_persists_to_disk(self, tmp_path):
        fake_path = str(tmp_path / "sessions.json")
        old_ts = (datetime.now(tz=UTC) - timedelta(days=31)).isoformat()

        data = [
            {"session_id": "old", "project": "p", "cwd": "/", "note": "n", "timestamp": old_ts},
        ]
        with open(fake_path, "w") as f:
            json.dump(data, f)

        with patch.object(bookmarks, "_PATH", fake_path):
            bookmarks.get_bookmarks()

        # File should now be empty list
        with open(fake_path) as f:
            on_disk = json.load(f)
        assert len(on_disk) == 0

    def test_recent_entries_kept(self, tmp_path):
        fake_path = str(tmp_path / "sessions.json")
        recent_ts = (datetime.now(tz=UTC) - timedelta(days=1)).isoformat()

        data = [
            {"session_id": "recent", "project": "p", "cwd": "/", "note": "n", "timestamp": recent_ts},
        ]
        with open(fake_path, "w") as f:
            json.dump(data, f)

        with patch.object(bookmarks, "_PATH", fake_path):
            result = bookmarks.get_bookmarks()

        assert len(result) == 1

    def test_entry_with_invalid_timestamp_kept(self, tmp_path):
        """Entries with unparseable timestamps survive pruning."""
        fake_path = str(tmp_path / "sessions.json")
        data = [
            {"session_id": "bad-ts", "project": "p", "cwd": "/", "note": "n", "timestamp": "not-a-date"},
        ]
        with open(fake_path, "w") as f:
            json.dump(data, f)

        with patch.object(bookmarks, "_PATH", fake_path):
            result = bookmarks.get_bookmarks()

        assert len(result) == 1
        assert result[0]["session_id"] == "bad-ts"

    def test_entry_with_missing_timestamp_kept(self, tmp_path):
        """Entries with no timestamp field survive pruning."""
        fake_path = str(tmp_path / "sessions.json")
        data = [
            {"session_id": "no-ts", "project": "p", "cwd": "/", "note": "n"},
        ]
        with open(fake_path, "w") as f:
            json.dump(data, f)

        with patch.object(bookmarks, "_PATH", fake_path):
            result = bookmarks.get_bookmarks()

        assert len(result) == 1


class TestBookmarkEmptyFileHandling:
    """Edge cases with missing or malformed files."""

    def test_nonexistent_file_returns_empty(self, tmp_path):
        fake_path = str(tmp_path / "does-not-exist.json")
        with patch.object(bookmarks, "_PATH", fake_path):
            result = bookmarks.get_bookmarks()
        assert result == []

    def test_empty_file_returns_empty(self, tmp_path):
        fake_path = str(tmp_path / "sessions.json")
        with open(fake_path, "w") as f:
            f.write("")

        with patch.object(bookmarks, "_PATH", fake_path):
            result = bookmarks.get_bookmarks()
        assert result == []

    def test_corrupt_json_returns_empty(self, tmp_path):
        fake_path = str(tmp_path / "sessions.json")
        with open(fake_path, "w") as f:
            f.write("{not valid json!!!")

        with patch.object(bookmarks, "_PATH", fake_path):
            result = bookmarks.get_bookmarks()
        assert result == []

    def test_json_object_instead_of_list_returns_empty(self, tmp_path):
        """File contains a JSON object instead of a list."""
        fake_path = str(tmp_path / "sessions.json")
        with open(fake_path, "w") as f:
            json.dump({"not": "a list"}, f)

        with patch.object(bookmarks, "_PATH", fake_path):
            result = bookmarks.get_bookmarks()
        assert result == []

    def test_non_dict_entries_skipped_during_pruning(self, tmp_path):
        """List entries that are not dicts are silently dropped during pruning."""
        fake_path = str(tmp_path / "sessions.json")
        recent_ts = datetime.now(tz=UTC).isoformat()
        data = [
            "just a string",
            42,
            {"session_id": "good", "project": "p", "cwd": "/", "note": "n", "timestamp": recent_ts},
        ]
        with open(fake_path, "w") as f:
            json.dump(data, f)

        with patch.object(bookmarks, "_PATH", fake_path):
            result = bookmarks.get_bookmarks()

        assert len(result) == 1
        assert result[0]["session_id"] == "good"

    def test_save_to_new_file_creates_it(self, tmp_path):
        fake_path = str(tmp_path / "brand-new.json")
        with patch.object(bookmarks, "_PATH", fake_path):
            bookmarks.save_bookmark("id-1", "proj", "/cwd", "note")

        with open(fake_path) as f:
            data = json.load(f)
        assert len(data) == 1
