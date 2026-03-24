"""Tests for claudewatch.backend.services.updates."""

import subprocess
from unittest.mock import MagicMock, patch

import claudewatch.backend.services.updates as _updates_mod
from claudewatch.backend.core.dto import UpdateInfoDTO
from claudewatch.backend.services.updates import (
    UpdateService,
    _get_download_url,
    _parse_version,
    check_for_update,
    get_cached_update,
)

MODULE = "claudewatch.backend.services.updates"


class TestParseVersion:
    def test_standard_tag(self):
        assert _parse_version("v1.2.3") == (1, 2, 3)

    def test_no_prefix(self):
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_prerelease_suffix_ignored(self):
        assert _parse_version("v1.2.3-beta.1") == (1, 2, 3)

    def test_garbage_returns_zero(self):
        assert _parse_version("garbage") == (0,)

    def test_two_part(self):
        assert _parse_version("v0.5") == (0, 5)

    def test_comparison_newer(self):
        assert _parse_version("v0.6.0") > _parse_version("v0.5.0")

    def test_comparison_same(self):
        assert _parse_version("v0.5.0") == _parse_version("0.5.0")

    def test_comparison_older(self):
        assert _parse_version("v0.4.0") < _parse_version("v0.5.0")


class TestUpdateService:
    """Tests for the UpdateService class."""

    def setup_method(self):
        self.svc = UpdateService()

    def test_check_newer_version_returns_dto(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v99.0.0\n"

        with patch(f"{MODULE}.subprocess.run", return_value=mock_result):
            result = self.svc.check()

        assert isinstance(result, UpdateInfoDTO)
        assert result.tag == "v99.0.0"
        assert result.download_url == _get_download_url("v99.0.0")

    def test_check_same_version_returns_none(self):
        with patch(f"{MODULE}.__version__", "0.5.0"):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "v0.5.0\n"

            with patch(f"{MODULE}.subprocess.run", return_value=mock_result):
                result = self.svc.check()

        assert result is None

    def test_check_older_version_returns_none(self):
        with patch(f"{MODULE}.__version__", "0.5.0"):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "v0.4.0\n"

            with patch(f"{MODULE}.subprocess.run", return_value=mock_result):
                result = self.svc.check()

        assert result is None

    def test_get_cached_returns_dto(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v99.0.0\n"

        with patch(f"{MODULE}.subprocess.run", return_value=mock_result):
            self.svc.check()

        cached = self.svc.get_cached()
        assert isinstance(cached, UpdateInfoDTO)
        assert cached.tag == "v99.0.0"

    def test_get_cached_returns_none_initially(self):
        assert self.svc.get_cached() is None

    def test_check_gh_fails_falls_back_to_curl(self):
        gh_result = MagicMock()
        gh_result.returncode = 1
        gh_result.stdout = ""

        curl_result = MagicMock()
        curl_result.returncode = 0
        curl_result.stdout = '{"tag_name": "v99.0.0"}'

        with patch(f"{MODULE}.subprocess.run", side_effect=[gh_result, curl_result]):
            result = self.svc.check()

        assert isinstance(result, UpdateInfoDTO)
        assert result.tag == "v99.0.0"

    def test_check_both_fail_returns_none(self):
        with patch(f"{MODULE}.subprocess.run", side_effect=FileNotFoundError):
            result = self.svc.check()

        assert result is None

    def test_check_timeout_returns_none(self):
        with patch(
            f"{MODULE}.subprocess.run",
            side_effect=subprocess.TimeoutExpired("cmd", 15),
        ):
            result = self.svc.check()

        assert result is None

    def test_check_caches_within_interval(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v99.0.0\n"

        with patch(f"{MODULE}.subprocess.run", return_value=mock_result) as mock_run:
            self.svc.check()
            self.svc.check()  # should use cache

        # gh called only once (first call)
        assert mock_run.call_count == 1

    def test_instances_have_independent_state(self):
        """Two UpdateService instances should not share cache state."""
        svc_a = UpdateService()
        svc_b = UpdateService()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v99.0.0\n"

        with patch(f"{MODULE}.subprocess.run", return_value=mock_result):
            svc_a.check()

        assert svc_a.get_cached() is not None
        assert svc_b.get_cached() is None

    def test_download_and_apply_no_bundle(self):
        with patch(f"{MODULE}._find_app_bundle", return_value=None):
            result = self.svc.download_and_apply("v1.0.0")

        assert result is False


class TestCheckForUpdate:
    """Tests for backward-compatible module-level functions."""

    def setup_method(self):
        _updates_mod._default_service._cached_update = None
        _updates_mod._default_service._last_check = 0.0

    def test_newer_version_available(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v99.0.0\n"

        with patch(f"{MODULE}.subprocess.run", return_value=mock_result):
            result = check_for_update()

        assert result == {"tag": "v99.0.0"}
        assert get_cached_update() == {"tag": "v99.0.0"}

    def test_same_version_no_update(self):
        with patch(f"{MODULE}.__version__", "0.5.0"):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "v0.5.0\n"

            with patch(f"{MODULE}.subprocess.run", return_value=mock_result):
                result = check_for_update()

        assert result is None
        assert get_cached_update() is None

    def test_older_version_no_update(self):
        with patch(f"{MODULE}.__version__", "0.5.0"):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "v0.4.0\n"

            with patch(f"{MODULE}.subprocess.run", return_value=mock_result):
                result = check_for_update()

        assert result is None

    def test_gh_fails_falls_back_to_curl(self):
        gh_result = MagicMock()
        gh_result.returncode = 1
        gh_result.stdout = ""

        curl_result = MagicMock()
        curl_result.returncode = 0
        curl_result.stdout = '{"tag_name": "v99.0.0"}'

        with patch(f"{MODULE}.subprocess.run", side_effect=[gh_result, curl_result]):
            result = check_for_update()

        assert result == {"tag": "v99.0.0"}

    def test_both_fail_returns_none(self):
        with patch(f"{MODULE}.subprocess.run", side_effect=FileNotFoundError):
            result = check_for_update()

        assert result is None

    def test_timeout_returns_none(self):
        with patch(
            f"{MODULE}.subprocess.run",
            side_effect=subprocess.TimeoutExpired("cmd", 15),
        ):
            result = check_for_update()

        assert result is None

    def test_caches_within_interval(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "v99.0.0\n"

        with patch(f"{MODULE}.subprocess.run", return_value=mock_result) as mock_run:
            check_for_update()
            check_for_update()  # should use cache

        # gh called only once (first call)
        assert mock_run.call_count == 1
