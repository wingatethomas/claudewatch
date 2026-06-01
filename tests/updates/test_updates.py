"""Tests for claudewatch.backend.updates.service."""

import subprocess
from unittest.mock import MagicMock, patch

from claudewatch.backend.core.dto import UpdateInfoDTO
from claudewatch.backend.core.features import Feature, register
from claudewatch.backend.updates.service import (
    UpdateService,
    _get_download_url,
    _parse_version,
)

MODULE = "claudewatch.backend.updates.service"


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
        register(Feature("auto_updates", "Automatic update checks"))
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

    def test_download_refuses_install_without_checksum(self, tmp_path):
        """If checksums.txt can't be fetched, the install must abort."""
        download_result = MagicMock(returncode=0, stderr="")
        with (
            patch(f"{MODULE}._find_app_bundle", return_value="/Applications/ClaudeWatch.app"),
            patch(f"{MODULE}.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch(f"{MODULE}.subprocess.run", return_value=download_result) as mock_run,
            patch(f"{MODULE}._fetch_expected_checksum", return_value=None),
            patch(f"{MODULE}._sha256_file") as mock_sha,
        ):
            # Pre-populate the would-be zip so the function gets past the download step.
            (tmp_path / "update.zip").write_bytes(b"fake-zip")
            result = self.svc.download_and_apply("v1.0.0")
        assert result is False
        mock_sha.assert_not_called()  # never compute a hash we can't verify against
        assert mock_run.called

    def test_download_refuses_install_on_checksum_mismatch(self, tmp_path):
        """A real checksum that doesn't match the zip's hash must abort the install."""
        download_result = MagicMock(returncode=0, stderr="")
        with (
            patch(f"{MODULE}._find_app_bundle", return_value="/Applications/ClaudeWatch.app"),
            patch(f"{MODULE}.tempfile.mkdtemp", return_value=str(tmp_path)),
            patch(f"{MODULE}.subprocess.run", return_value=download_result),
            patch(f"{MODULE}._fetch_expected_checksum", return_value="a" * 64),
            patch(f"{MODULE}._sha256_file", return_value="b" * 64),
        ):
            (tmp_path / "update.zip").write_bytes(b"fake-zip")
            result = self.svc.download_and_apply("v1.0.0")
        assert result is False
