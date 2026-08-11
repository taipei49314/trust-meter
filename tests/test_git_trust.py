"""Tests for git integration."""

from trust_meter.git_trust import (
    current_commit_info, commit_history, changed_files,
    is_dirty, branch_name, trust_tag, format_commit_with_trust,
    git_log_with_trust, CommitInfo,
)


def test_current_commit_info():
    info = current_commit_info(".")
    # May be None if not in a git repo, or should have valid fields
    if info:
        assert len(info.hash) == 40
        assert len(info.short_hash) >= 4
        assert info.author
        assert info.message


def test_commit_history():
    history = commit_history(".", count=5)
    assert isinstance(history, list)
    if history:
        assert len(history) <= 5
        assert all(isinstance(c, CommitInfo) for c in history)


def test_changed_files():
    files = changed_files(".")
    assert isinstance(files, list)
    # All should be .py files
    assert all(f.endswith(".py") for f in files)


def test_is_dirty():
    result = is_dirty(".")
    assert isinstance(result, bool)


def test_branch_name():
    name = branch_name(".")
    assert isinstance(name, str)


def test_trust_tag():
    tag = trust_tag(".", 95.0)
    assert "trust:" in tag
    assert "95" in tag


def test_format_commit_with_trust():
    commit = CommitInfo("abc123", "abc123", "test", "2026-01-01", "initial commit")
    line = format_commit_with_trust(commit, 100.0)
    assert "abc123" in line
    assert "[100]" in line
    assert "initial commit" in line


def test_format_commit_without_trust():
    commit = CommitInfo("abc123", "abc123", "test", "2026-01-01", "initial commit")
    line = format_commit_with_trust(commit)
    assert "abc123" in line
    assert "[" not in line


def test_git_log_with_trust():
    lines = git_log_with_trust(".", count=3)
    assert isinstance(lines, list)
    assert len(lines) <= 3


def test_git_log_with_scores():
    scores = {"abc123": 95.0}
    lines = git_log_with_trust(".", count=1, scores=scores)
    assert isinstance(lines, list)
