"""Trustignore: gitignore-style pattern exclusion.

Supports:
- * — match any characters except path separator
- ** — match any characters including path separator
- ? — match single character
- !pattern — negation (un-ignore)
- # — comments
- trailing / — directory-only pattern

Usage:
    patterns = load_trustignore(Path("."))
    if is_ignored("vendor/lib.py", patterns):
        skip()
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

TRUSTIGNORE_FILENAME = ".trustignore"


def load_trustignore(root: Path) -> list[str]:
    """Load patterns from .trustignore file."""
    ignore_file = root / TRUSTIGNORE_FILENAME
    if not ignore_file.exists():
        return []

    patterns: list[str] = []
    for line in ignore_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


def _pattern_to_regex(pattern: str) -> str:
    """Convert a gitignore-style pattern to a regex string."""
    negated = False
    if pattern.startswith("!"):
        negated = True
        pattern = pattern[1:]

    # Escape special regex chars except * and ?
    result = ""
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*" and i + 1 < len(pattern) and pattern[i + 1] == "*":
            result += ".*"
            i += 2
            # Skip optional / after **
            if i < len(pattern) and pattern[i] == "/":
                i += 1
        elif c == "*":
            result += "[^/]*"
            i += 1
        elif c == "?":
            result += "[^/]"
            i += 1
        elif c in ".+^${}()|[]\\":
            result += "\\" + c
            i += 1
        else:
            result += c
            i += 1

    # Directory pattern: match the directory itself and everything inside
    if pattern.endswith("/"):
        result = result.rstrip("/") + "(/.*)?$"
    else:
        # Match file or directory
        result = result + "(/.*)?$"

    prefix = "!" if negated else ""
    return prefix + "^" + result


def _match_pattern(pattern: str, rel_path: str) -> bool:
    """Check if a single pattern matches a path.

    Gitignore semantics:
    - Pattern without / matches filename at any depth
    - Pattern with / matches from the root
    """
    negated = pattern.startswith("!")
    if negated:
        pattern = pattern[1:]

    # Convert pattern to regex
    regex_str = _pattern_to_regex(pattern)
    if regex_str.startswith("!"):
        regex_str = regex_str[1:]

    has_slash = "/" in pattern.rstrip("/")

    if has_slash:
        # Pattern with /: match from root
        return bool(re.match(regex_str, rel_path, re.IGNORECASE))
    else:
        # Pattern without /: match against each path component
        parts = rel_path.split("/")
        for part in parts:
            if re.match(regex_str, part, re.IGNORECASE):
                return True
        return False


def is_ignored(rel_path: str, patterns: list[str]) -> bool:
    """Check if a relative path matches any ignore pattern.

    Returns True if the path should be ignored.
    Last matching pattern wins (like gitignore).
    """
    if not patterns:
        return False

    rel_path = rel_path.replace("\\", "/")

    ignored = False
    for raw_pattern in patterns:
        negated = raw_pattern.startswith("!")
        pattern = raw_pattern[1:] if negated else raw_pattern

        if _match_pattern(pattern, rel_path):
            ignored = not negated

    return ignored


def filter_paths(paths: list[str], patterns: list[str]) -> list[str]:
    """Filter a list of relative paths, removing ignored ones."""
    return [p for p in paths if not is_ignored(p, patterns)]
