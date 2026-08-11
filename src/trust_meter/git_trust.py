"""Git integration: trust operations with git history.

Provides:
- Current commit trust score
- Trust history across commits
- Branch comparison
- Trust-annotated git log

Usage:
    from trust_meter.git_trust import current_commit_info, trust_history
    info = current_commit_info(Path("."))
    history = trust_history(Path("."), count=10)
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommitInfo:
    """Git commit metadata."""

    hash: str
    short_hash: str
    author: str
    date: str
    message: str


def current_commit_info(repo_root: Path) -> CommitInfo | None:
    """Get current HEAD commit info."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H|%h|%an|%ai|%s"],
            capture_output=True, text=True, cwd=str(repo_root), close_fds=True, errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            return None
        parts = result.stdout.strip().split("|", 4)
        if len(parts) < 5:
            return None
        return CommitInfo(
            hash=parts[0], short_hash=parts[1],
            author=parts[2], date=parts[3], message=parts[4],
        )
    except Exception:
        return None


def commit_history(repo_root: Path, count: int = 10) -> list[CommitInfo]:
    """Get recent commit history."""
    try:
        result = subprocess.run(
            ["git", "log", f"-{count}", "--format=%H|%h|%an|%ai|%s"],
            capture_output=True, text=True, cwd=str(repo_root), close_fds=True, errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            return []
        commits: list[CommitInfo] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("|", 4)
            if len(parts) >= 5:
                commits.append(CommitInfo(
                    hash=parts[0], short_hash=parts[1],
                    author=parts[2], date=parts[3], message=parts[4],
                ))
        return commits
    except Exception:
        return []


def changed_files(repo_root: Path, ref: str = "HEAD") -> list[str]:
    """Get files changed in a commit."""
    try:
        result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", ref],
            capture_output=True, text=True, cwd=str(repo_root), close_fds=True, errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            return []
        return [f for f in result.stdout.strip().splitlines() if f.endswith(".py")]
    except Exception:
        return []


def is_dirty(repo_root: Path) -> bool:
    """Check if the working tree has uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(repo_root), close_fds=True, errors="replace",
            timeout=10,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def branch_name(repo_root: Path) -> str:
    """Get current branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=str(repo_root), close_fds=True, errors="replace",
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def trust_tag(repo_root: Path, score: float) -> str:
    """Generate a trust tag string for a commit."""
    info = current_commit_info(repo_root)
    if not info:
        return f"trust:{score:.0f}"
    return f"trust:{score:.0f}@{info.short_hash}"


def format_commit_with_trust(commit: CommitInfo, score: float | None = None) -> str:
    """Format a commit line with optional trust score."""
    trust = f" [{score:.0f}]" if score is not None else ""
    return f"{commit.short_hash} {commit.date[:10]} {commit.message}{trust}"


def git_log_with_trust(repo_root: Path, count: int = 10, scores: dict[str, float] | None = None) -> list[str]:
    """Format git log with optional trust scores."""
    commits = commit_history(repo_root, count)
    lines: list[str] = []
    for c in commits:
        score = scores.get(c.hash) if scores else None
        lines.append(format_commit_with_trust(c, score))
    return lines
