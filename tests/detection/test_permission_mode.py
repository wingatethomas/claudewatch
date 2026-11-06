"""Tests for permission-mode capture and the just-finished flag."""

import json
import os
from unittest.mock import MagicMock

from claudewatch.backend.core.models import SessionStatus
from claudewatch.backend.core.session_log.jsonl import latest_permission_mode, read_permission_mode_head
from claudewatch.backend.core.session_log.service import SessionLogService
from claudewatch.backend.detection.service import DetectionService
from tests.detection.test_detect_integration import _build_service, _cwd_to_proj_dir, _write_jsonl

_ASSISTANT = {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}


def _mode_entry(mode: str) -> dict:
    return {"type": "permission-mode", "permissionMode": mode}


class TestLatestPermissionMode:
    def test_single_entry(self) -> None:
        lines = [json.dumps(_mode_entry("auto"))]
        assert latest_permission_mode(lines) == "auto"

    def test_latest_wins_on_mid_session_change(self) -> None:
        lines = [json.dumps(_mode_entry("default")), json.dumps(_ASSISTANT), json.dumps(_mode_entry("auto"))]
        assert latest_permission_mode(lines) == "auto"

    def test_no_entry(self) -> None:
        assert latest_permission_mode([json.dumps(_ASSISTANT)]) == ""

    def test_malformed_lines_skipped(self) -> None:
        lines = ['{"type":"permission-mode" broken', json.dumps(_mode_entry("auto"))]
        assert latest_permission_mode(lines) == "auto"

    def test_non_string_value_ignored(self) -> None:
        lines = [json.dumps({"type": "permission-mode", "permissionMode": 7})]
        assert latest_permission_mode(lines) == ""


class TestReadPermissionModeHead:
    def test_entry_in_head(self, tmp_path) -> None:
        path = tmp_path / "s.jsonl"
        _write_jsonl(str(path), [_mode_entry("auto"), _ASSISTANT])
        assert read_permission_mode_head(str(path)) == "auto"

    def test_entry_past_max_lines(self, tmp_path) -> None:
        path = tmp_path / "s.jsonl"
        _write_jsonl(str(path), [_ASSISTANT] * 12 + [_mode_entry("auto")])
        assert read_permission_mode_head(str(path)) == ""

    def test_missing_file(self, tmp_path) -> None:
        assert read_permission_mode_head(str(tmp_path / "gone.jsonl")) == ""

    def test_corrupt_head_lines_skipped(self, tmp_path) -> None:
        path = tmp_path / "s.jsonl"
        path.write_text("garbage\n" + json.dumps(_mode_entry("default")) + "\n")
        assert read_permission_mode_head(str(path)) == "default"


class TestGetPermissionModeCache:
    def _service(self) -> tuple[DetectionService, MagicMock]:
        session_log = MagicMock(spec=SessionLogService)
        session_log.read_permission_mode_head.return_value = ""
        svc = DetectionService(MagicMock(), session_log)
        return svc, session_log

    def test_tail_value_wins_and_caches(self) -> None:
        svc, session_log = self._service()
        tail = json.dumps(_mode_entry("auto"))
        assert svc._get_permission_mode("/p/s.jsonl", tail) == "auto"
        assert svc._permission_mode_by_path["/p/s.jsonl"] == "auto"
        session_log.read_permission_mode_head.assert_not_called()

    def test_head_scan_once_then_cached(self) -> None:
        svc, session_log = self._service()
        session_log.read_permission_mode_head.return_value = "auto"
        assert svc._get_permission_mode("/p/s.jsonl", "") == "auto"
        assert svc._get_permission_mode("/p/s.jsonl", "") == "auto"
        session_log.read_permission_mode_head.assert_called_once()

    def test_empty_head_result_not_cached(self) -> None:
        svc, session_log = self._service()
        assert svc._get_permission_mode("/p/s.jsonl", "") == ""
        assert "/p/s.jsonl" not in svc._permission_mode_by_path
        assert svc._get_permission_mode("/p/s.jsonl", "") == ""
        assert session_log.read_permission_mode_head.call_count == 2

    def test_tail_change_overrides_cache(self) -> None:
        svc, _ = self._service()
        svc._permission_mode_by_path["/p/s.jsonl"] = "default"
        tail = json.dumps(_mode_entry("auto"))
        assert svc._get_permission_mode("/p/s.jsonl", tail) == "auto"
        assert svc._permission_mode_by_path["/p/s.jsonl"] == "auto"


class TestJustFinishedFlag:
    def _detect(self, tmp_path, entries: list[dict], age_seconds: float, *, title: str = "autoproj — ✳ claude"):
        from claudewatch.backend.core.process.models import ProcessInfo

        cwd = "/Users/dev/autoproj"
        proj_dir = _cwd_to_proj_dir(str(tmp_path), cwd)
        _write_jsonl(os.path.join(proj_dir, "s1.jsonl"), entries, age_seconds=age_seconds)
        svc = _build_service(
            str(tmp_path),
            [100],
            pid_info={100: ProcessInfo(tty="ttys001", ppid=1, comm="claude")},
            pid_cwds={100: cwd},
            terminal_titles={"/dev/ttys001": (title, 1)},
        )
        try:
            return svc.detect()
        finally:
            for p in svc._test_patchers:
                p.stop()

    def test_auto_idle_recent_is_just_finished(self, tmp_path) -> None:
        sessions = self._detect(tmp_path, [_mode_entry("auto"), _ASSISTANT], age_seconds=120)
        assert len(sessions) == 1
        assert sessions[0].status == SessionStatus.IDLE
        assert sessions[0].permission_mode == "auto"
        assert sessions[0].just_finished is True

    def test_auto_idle_old_is_not_just_finished(self, tmp_path) -> None:
        sessions = self._detect(tmp_path, [_mode_entry("auto"), _ASSISTANT], age_seconds=3610)
        assert sessions[0].just_finished is False

    def test_auto_idle_inside_window_boundary(self, tmp_path) -> None:
        sessions = self._detect(tmp_path, [_mode_entry("auto"), _ASSISTANT], age_seconds=3590)
        assert sessions[0].just_finished is True

    def test_default_mode_never_just_finished(self, tmp_path) -> None:
        sessions = self._detect(tmp_path, [_mode_entry("default"), _ASSISTANT], age_seconds=120)
        assert sessions[0].permission_mode == "default"
        assert sessions[0].just_finished is False

    def test_working_auto_session_not_just_finished(self, tmp_path) -> None:
        sessions = self._detect(
            tmp_path,
            [_mode_entry("auto"), _ASSISTANT],
            age_seconds=0,
            title="autoproj — ⠋ claude",
        )
        assert sessions[0].status == SessionStatus.WORKING
        assert sessions[0].just_finished is False

    def test_mid_session_toggle_latest_wins(self, tmp_path) -> None:
        entries = [_mode_entry("default"), _ASSISTANT, _mode_entry("auto"), _ASSISTANT]
        sessions = self._detect(tmp_path, entries, age_seconds=120)
        assert sessions[0].permission_mode == "auto"
        assert sessions[0].just_finished is True
