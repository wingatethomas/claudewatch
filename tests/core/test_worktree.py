"""Tests for claudewatch.backend.core.worktree."""

import os

from claudewatch.backend.core.worktree import resolve_worktree


def _make_repo_with_worktree(tmp_path, *, branch="feature-x", detached_sha="", relative_gitdir=False):
    """Lay out a main repo plus a linked worktree the way git does."""
    repo = tmp_path / "myrepo"
    wt_admin = repo / ".git" / "worktrees" / "wt1"
    wt_admin.mkdir(parents=True)
    if detached_sha:
        (wt_admin / "HEAD").write_text(f"{detached_sha}\n")
    else:
        (wt_admin / "HEAD").write_text(f"ref: refs/heads/{branch}\n")

    worktree = tmp_path / "worktrees" / "wt1"
    worktree.mkdir(parents=True)
    gitdir = os.path.relpath(wt_admin, worktree) if relative_gitdir else str(wt_admin)
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n")
    return worktree


class TestResolveWorktree:
    def test_linked_worktree_resolves_repo_and_branch(self, tmp_path):
        worktree = _make_repo_with_worktree(tmp_path, branch="thomas/some-fix")
        info = resolve_worktree(str(worktree))
        assert info is not None
        assert info.repo == "myrepo"
        assert info.branch == "thomas/some-fix"

    def test_resolves_from_subdirectory(self, tmp_path):
        worktree = _make_repo_with_worktree(tmp_path)
        sub = worktree / "src" / "pkg"
        sub.mkdir(parents=True)
        info = resolve_worktree(str(sub))
        assert info is not None
        assert info.repo == "myrepo"

    def test_relative_gitdir_pointer(self, tmp_path):
        worktree = _make_repo_with_worktree(tmp_path, relative_gitdir=True)
        info = resolve_worktree(str(worktree))
        assert info is not None
        assert info.repo == "myrepo"
        assert info.branch == "feature-x"

    def test_detached_head_uses_short_sha(self, tmp_path):
        worktree = _make_repo_with_worktree(tmp_path, detached_sha="a" * 40)
        info = resolve_worktree(str(worktree))
        assert info is not None
        assert info.branch == "a" * 8

    def test_missing_head_yields_empty_branch(self, tmp_path):
        worktree = _make_repo_with_worktree(tmp_path)
        os.remove(tmp_path / "myrepo" / ".git" / "worktrees" / "wt1" / "HEAD")
        info = resolve_worktree(str(worktree))
        assert info is not None
        assert info.branch == ""

    def test_regular_checkout_is_not_a_worktree(self, tmp_path):
        repo = tmp_path / "regular"
        (repo / ".git").mkdir(parents=True)
        assert resolve_worktree(str(repo)) is None

    def test_submodule_style_git_file_is_not_a_worktree(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / ".git").write_text("gitdir: ../.git/modules/sub\n")
        assert resolve_worktree(str(sub)) is None

    def test_no_git_anywhere(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert resolve_worktree(str(plain)) is None

    def test_empty_and_missing_cwd(self):
        assert resolve_worktree("") is None
        assert resolve_worktree("/nonexistent/nowhere") is None
