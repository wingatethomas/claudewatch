"""Git worktree recognition from filesystem metadata — no subprocesses.

Linked worktrees have a ``.git`` file (not a directory) whose ``gitdir:``
line points into ``<repo>/.git/worktrees/<name>``. Recognizing one costs
two small file reads, cheap enough for the detection poll loop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_MAX_WALK_UP = 8
_WORKTREES_MARKER = f"{os.sep}.git{os.sep}worktrees{os.sep}"
_DETACHED_SHA_LEN = 8


@dataclass(frozen=True)
class WorktreeInfo:
    """A session cwd resolved to its main repository and checked-out branch."""

    repo: str
    branch: str  # short SHA when detached, "" when unreadable


def resolve_worktree(cwd: str) -> WorktreeInfo | None:
    """Return WorktreeInfo when cwd is inside a linked git worktree, else None.

    Regular checkouts (``.git`` directory), bare repos, and submodules
    (``.git`` file without the worktrees marker) all resolve to None.
    """
    if not cwd:
        return None
    root = _find_git_entry(cwd)
    if not root:
        return None
    git_path = os.path.join(root, ".git")
    if not os.path.isfile(git_path):
        return None
    gitdir = _read_gitdir(git_path)
    if _WORKTREES_MARKER not in gitdir:
        return None
    repo_root = gitdir.split(_WORKTREES_MARKER, 1)[0]
    return WorktreeInfo(repo=os.path.basename(repo_root), branch=_read_branch(gitdir))


def _find_git_entry(start: str) -> str | None:
    """Walk up from start looking for a directory containing ``.git``."""
    path = os.path.abspath(start)
    for _ in range(_MAX_WALK_UP):
        if os.path.lexists(os.path.join(path, ".git")):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    return None


def _read_gitdir(git_file: str) -> str:
    """Parse the ``gitdir:`` pointer from a ``.git`` file (resolves relative paths)."""
    try:
        with open(git_file) as f:
            line = f.readline().strip()
    except OSError:
        return ""
    if not line.startswith("gitdir:"):
        return ""
    gitdir = line.removeprefix("gitdir:").strip()
    if not os.path.isabs(gitdir):
        gitdir = os.path.normpath(os.path.join(os.path.dirname(git_file), gitdir))
    return gitdir


def _read_branch(gitdir: str) -> str:
    """Read the checked-out branch from the worktree's HEAD file."""
    try:
        with open(os.path.join(gitdir, "HEAD")) as f:
            head = f.readline().strip()
    except OSError:
        return ""
    if head.startswith("ref: refs/heads/"):
        return head.removeprefix("ref: refs/heads/")
    return head[:_DETACHED_SHA_LEN]
