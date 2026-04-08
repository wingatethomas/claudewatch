"""Tests for git remote resolver."""

from claudewatch.backend.analytics.git_resolver import parse_remote_url


class TestParseRemoteUrl:
    def test_ssh_github(self) -> None:
        assert parse_remote_url("git@github.com:org/repo.git") == "org/repo"

    def test_ssh_github_no_git_suffix(self) -> None:
        assert parse_remote_url("git@github.com:org/repo") == "org/repo"

    def test_https_github(self) -> None:
        assert parse_remote_url("https://github.com/org/repo.git") == "org/repo"

    def test_https_no_git_suffix(self) -> None:
        assert parse_remote_url("https://github.com/org/repo") == "org/repo"

    def test_ssh_protocol_gitlab(self) -> None:
        assert parse_remote_url("ssh://git@gitlab.com/org/repo.git") == "org/repo"

    def test_nested_org(self) -> None:
        assert parse_remote_url("git@github.com:org/sub/repo.git") == "org/sub/repo"

    def test_unknown_format(self) -> None:
        assert parse_remote_url("/local/path/to/repo") == "/local/path/to/repo"

    def test_empty_string(self) -> None:
        assert parse_remote_url("") == ""
