"""Tests for the trustignore module."""

import tempfile
from pathlib import Path

from trust_meter.ignore import (
    load_trustignore, is_ignored, filter_paths,
    _pattern_to_regex,
)


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_load_trustignore():
    d = _make_project({
        ".trustignore": "vendor/*\n# comment\n*.pyc\n",
    })
    patterns = load_trustignore(d)
    assert patterns == ["vendor/*", "*.pyc"]


def test_load_trustignore_no_file():
    d = _make_project({})
    patterns = load_trustignore(d)
    assert patterns == []


def test_load_trustignore_empty_lines():
    d = _make_project({
        ".trustignore": "vendor/*\n\n\n*.pyc\n",
    })
    patterns = load_trustignore(d)
    assert len(patterns) == 2


def test_is_ignored_simple():
    assert is_ignored("vendor/lib.py", ["vendor/*"]) is True
    assert is_ignored("src/main.py", ["vendor/*"]) is False


def test_is_ignored_wildcard():
    assert is_ignored("src/test.pyc", ["*.pyc"]) is True
    assert is_ignored("src/main.py", ["*.pyc"]) is False


def test_is_ignored_directory():
    assert is_ignored("vendor/lib.py", ["vendor/"]) is True
    assert is_ignored("vendor/sub/deep.py", ["vendor/"]) is True
    assert is_ignored("src/main.py", ["vendor/"]) is False


def test_is_ignored_double_star():
    assert is_ignored("a/b/c/deep.py", ["**/deep.py"]) is True
    assert is_ignored("deep.py", ["**/deep.py"]) is True
    assert is_ignored("a/b/c/other.py", ["**/deep.py"]) is False


def test_is_ignored_negation():
    patterns = ["vendor/*", "!vendor/important.py"]
    assert is_ignored("vendor/lib.py", patterns) is True
    assert is_ignored("vendor/important.py", patterns) is False


def test_is_ignored_negation_last_wins():
    patterns = ["*.py", "!special.py", "special.py"]
    # Last matching pattern wins
    assert is_ignored("special.py", patterns) is True


def test_is_ignored_question_mark():
    assert is_ignored("test1.py", ["test?.py"]) is True
    assert is_ignored("test12.py", ["test?.py"]) is False


def test_is_ignored_no_patterns():
    assert is_ignored("any/path.py", []) is False


def test_filter_paths():
    patterns = ["vendor/*", "*.pyc"]
    paths = ["src/main.py", "vendor/lib.py", "build/out.pyc", "src/utils.py"]
    result = filter_paths(paths, patterns)
    assert result == ["src/main.py", "src/utils.py"]


def test_filter_paths_empty():
    assert filter_paths(["a.py"], []) == ["a.py"]
    assert filter_paths([], ["*.py"]) == []


def test_pattern_to_regex_simple():
    regex = _pattern_to_regex("vendor/*")
    assert "vendor" in regex
    assert "*" in regex or "[^/]*" in regex


def test_pattern_to_regex_negation():
    regex = _pattern_to_regex("!important.py")
    assert regex.startswith("!")


def test_is_ignored_nested_dir():
    assert is_ignored("node_modules/package/index.js", ["node_modules/"]) is True
    # In gitignore, node_modules/ matches at any depth
    assert is_ignored("src/node_modules/pkg/index.js", ["node_modules/"]) is True


def test_is_ignored_case_insensitive():
    # Should be case-insensitive on Windows
    assert is_ignored("Vendor/lib.py", ["vendor/*"]) is True


def test_load_trustignore_with_negation():
    d = _make_project({
        ".trustignore": "generated/*\n!generated/keep.py\n",
    })
    patterns = load_trustignore(d)
    assert len(patterns) == 2
    assert patterns[0] == "generated/*"
    assert patterns[1] == "!generated/keep.py"
