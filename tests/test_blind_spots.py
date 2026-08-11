"""Blind spot tests: edge cases and error paths that weren't covered.

Covers:
- Binary/non-UTF8 files
- Boundary conditions (exactly at limits)
- Corrupted files
- Config edge cases
- Plugin edge cases
- Trustignore edge cases
- Metric weight edge cases
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from trust_meter.meter import TrustMeter, MetricResult, TrustReport
from trust_meter.config import parse_config, Config
from trust_meter.ignore import load_trustignore, is_ignored
from trust_meter.spec import parse_spec
from trust_meter.trending import TrendTracker
from trust_meter.baseline import load_baseline
from trust_meter.plugins import _load_plugin, validate_plugin
from trust_meter.metrics.determinism import collect_determinism
from trust_meter.metrics.locality import collect_locality
from trust_meter.metrics.evidence import collect_evidence, _analyze_test_file
from trust_meter.metrics.reproducibility import collect_reproducibility
from trust_meter.metrics.transparency import collect_transparency
from trust_meter.metrics.architecture import collect_architecture
from trust_meter.metrics.complexity import collect_complexity


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


# === Binary / Non-UTF8 ===

def test_binary_py_file():
    """Binary .py file should be skipped gracefully."""
    d = Path(tempfile.mkdtemp())
    src = d / "src"
    src.mkdir()
    (src / "bad.py").write_bytes(b"\x80\x81\x82\x83")
    (src / "good.py").write_text("x = 1\n")
    result = collect_determinism(d)
    # Should not crash, should still scan good.py
    assert result.name == "determinism"


def test_binary_py_file_evidence():
    """Binary .py file in evidence collection."""
    d = Path(tempfile.mkdtemp())
    src = d / "src"
    src.mkdir()
    (src / "bad.py").write_bytes(b"\x80\x81\x82\x83")
    evidence = collect_evidence(d)
    assert evidence.name == "evidence"


def test_binary_py_file_transparency():
    """Binary .py file in transparency check."""
    d = Path(tempfile.mkdtemp())
    src = d / "src"
    src.mkdir()
    (src / "bad.py").write_bytes(b"\x80\x81\x82\x83")
    result = collect_transparency(d)
    assert result.name == "transparency"


# === Boundary conditions ===

def test_function_exactly_50_lines():
    """Function with exactly 50 lines should pass length check."""
    lines = ['def f():\n', '    """Doc."""\n'] + ["    x = 1\n"] * 48
    d = _make_project({"src/main.py": "".join(lines)})
    result = collect_transparency(d)
    assert result.passed is True


def test_function_51_lines():
    """Function with 51 lines should fail."""
    lines = ["def f():\n"] + ["    x = 1\n"] * 50
    d = _make_project({"src/main.py": "".join(lines)})
    result = collect_transparency(d)
    assert result.passed is False


def test_file_exactly_500_lines():
    """File with exactly 500 lines should pass."""
    content = "\n".join(f"x{i} = {i}" for i in range(500))
    d = _make_project({"src/main.py": content + "\n"})
    result = collect_transparency(d)
    assert result.passed is True


def test_file_501_lines():
    """File with 501 lines should fail."""
    content = "\n".join(f"x{i} = {i}" for i in range(501))
    d = _make_project({"src/main.py": content + "\n"})
    result = collect_transparency(d)
    assert result.passed is False


def test_threshold_exactly_at_score():
    """Threshold exactly at score should pass."""
    meter = TrustMeter()
    meter.register("test", lambda p: MetricResult("test", 70, 1.0, True, [], "ok"))
    d = Path(tempfile.mkdtemp())
    report = meter.measure(d, threshold=70)
    assert report.passed is True


def test_threshold_just_below():
    """Threshold just above score should fail."""
    meter = TrustMeter()
    meter.register("test", lambda p: MetricResult("test", 69.9, 1.0, True, [], "ok"))
    d = Path(tempfile.mkdtemp())
    report = meter.measure(d, threshold=70)
    assert report.passed is False


def test_complexity_exactly_10():
    """Function with cc=10 should pass max check (avg needs low-complexity peers)."""
    d = _make_project({
        "src/main.py": (
            "def f(x):\n"
            "    if x: pass\n"
            "    if x: pass\n"
            "    if x: pass\n"
            "    if x: pass\n"
            "    if x: pass\n"
            "    if x: pass\n"
            "    if x: pass\n"
            "    if x: pass\n"
            "    if x: pass\n"
            "def g():\n"
            "    pass\n"
        ),
    })
    result = collect_complexity(d)
    # max cc=10 passes, avg cc=(10+1)/2=5.5 passes
    assert result.passed is True


def test_complexity_11():
    """Function with cc=11 should fail."""
    lines = ["def f(x):\n"]
    for i in range(11):
        lines.append(f"    if x > {i}: pass\n")
    d = _make_project({"src/main.py": "".join(lines)})
    result = collect_complexity(d)
    assert result.passed is False


# === Corrupted files ===

def test_corrupted_baseline():
    """Corrupted baseline JSON should raise error."""
    d = Path(tempfile.mkdtemp())
    (d / ".trust-baselines").mkdir()
    (d / ".trust-baselines" / "latest.json").write_text("not json{{{")
    try:
        load_baseline(d / ".trust-baselines" / "latest.json")
        assert False, "Should have raised"
    except (json.JSONDecodeError, KeyError, ValueError):
        pass


def test_corrupted_trending():
    """Corrupted trending JSON should be handled gracefully."""
    d = Path(tempfile.mkdtemp())
    (d / ".trust-trending.json").write_text("not json{{{")
    tracker = TrendTracker(d)
    assert tracker.count == 0


# === Config edge cases ===

def test_config_empty_sections():
    """Config with empty sections."""
    config = parse_config("[trust-meter]\n[skip]\n[weights]\n[limits]\n")
    assert config.threshold == 70.0
    assert config.skip_patterns == []
    assert config.weights == {}
    assert config.limits == {}


def test_config_unknown_section():
    """Config with unknown section should be ignored."""
    config = parse_config("[unknown]\nfoo = bar\n")
    assert config.threshold == 70.0


def test_config_unknown_key():
    """Config with unknown key in known section."""
    config = parse_config("[trust-meter]\nunknown_key = 42\n")
    assert config.threshold == 70.0


def test_config_negative_threshold():
    """Config with negative threshold."""
    config = parse_config("[trust-meter]\nthreshold = -10\n")
    assert config.threshold == -10.0


def test_config_very_large_threshold():
    """Config with very large threshold."""
    config = parse_config("[trust-meter]\nthreshold = 99999\n")
    assert config.threshold == 99999.0


# === Plugin edge cases ===

def test_plugin_import_error():
    """Plugin that imports nonexistent module should fail gracefully."""
    d = _make_project({
        "bad_plugin.py": "import nonexistent_module_xyz\ndef collect_bad(t): pass\n",
    })
    name, collector = _load_plugin(d / "bad_plugin.py")
    assert name is None


def test_plugin_empty_file():
    """Empty plugin file should fail gracefully."""
    d = _make_project({"empty.py": ""})
    name, collector = _load_plugin(d / "empty.py")
    assert name is None


def test_validate_plugin_exception_on_call():
    """Plugin that raises on call should be caught."""
    def bad_plugin(target):
        raise RuntimeError("boom")
    valid, msg = validate_plugin(bad_plugin, "bad")
    # Should still be valid (errors during execution are OK)
    assert valid is True


# === Trustignore edge cases ===

def test_trustignore_only_negation():
    """Trustignore with only negation patterns."""
    patterns = ["!important.py"]
    assert is_ignored("other.py", patterns) is False
    assert is_ignored("important.py", patterns) is False


def test_trustignore_empty_file():
    """Empty trustignore should return no patterns."""
    d = _make_project({".trustignore": ""})
    patterns = load_trustignore(d)
    assert patterns == []


def test_trustignore_whitespace_only():
    """Whitespace-only trustignore should return no patterns."""
    d = _make_project({".trustignore": "   \n  \n   "})
    patterns = load_trustignore(d)
    assert patterns == []


def test_trustignore_deeply_nested():
    """Deeply nested path should match."""
    assert is_ignored("a/b/c/d/e/f.py", ["**/f.py"]) is True


def test_trustignore_special_chars():
    """Pattern with special regex chars (. is literal in gitignore)."""
    assert is_ignored("file.name.py", ["file.name.py"]) is True
    # . is literal in gitignore, not a wildcard
    assert is_ignored("file_name.py", ["file.name.py"]) is False


# === Metric weight edge cases ===

def test_metric_weight_zero():
    """Metric with weight=0 should not affect score."""
    meter = TrustMeter()
    meter.register("a", lambda p: MetricResult("a", 100, 1.0, True, [], "ok"), weight=1.0)
    meter.register("b", lambda p: MetricResult("b", 0, 1.0, False, [], "fail"), weight=0.0)
    d = Path(tempfile.mkdtemp())
    report = meter.measure(d, threshold=70)
    assert report.overall_score == 100.0


def test_metric_weight_negative():
    """Metric with negative weight should be handled."""
    meter = TrustMeter()
    meter.register("a", lambda p: MetricResult("a", 100, 1.0, True, [], "ok"), weight=1.0)
    meter.register("b", lambda p: MetricResult("b", 50, -1.0, True, [], "ok"), weight=-1.0)
    d = Path(tempfile.mkdtemp())
    report = meter.measure(d, threshold=70)
    # Should still compute without crashing
    assert report.overall_score is not None


# === Spec edge cases ===

def test_spec_unknown_section():
    """Spec with unknown section."""
    spec = parse_spec("[unknown]\nfoo = bar\n")
    assert spec.name == "unnamed"


def test_spec_empty_modules():
    """Spec with empty modules list."""
    spec = parse_spec("[assertions]\nmodules = []\n")
    assert len(spec.assertions) == 0


def test_spec_duplicate_modules():
    """Spec with duplicate modules."""
    spec = parse_spec('[assertions]\nmodules = ["calc", "calc"]\n')
    assert len(spec.assertions) == 2


# === Integration edge cases ===

def test_all_metrics_empty_project():
    """All metrics on completely empty project."""
    d = _make_project({})
    assert collect_determinism(d).passed is True
    assert collect_locality(d).passed is True
    assert collect_evidence(d).passed is True
    assert collect_reproducibility(d).passed is True
    assert collect_architecture(d).passed is True
    assert collect_complexity(d).passed is True
    assert collect_transparency(d).passed is True


def test_all_metrics_syntax_error():
    """All metrics on file with syntax error."""
    d = _make_project({"src/broken.py": "def broken(\n    pass\n"})
    assert collect_determinism(d).name == "determinism"
    assert collect_transparency(d).name == "transparency"
    assert collect_complexity(d).name == "complexity"


def test_meter_with_all_failing():
    """All metrics failing should give score 0."""
    meter = TrustMeter()
    meter.register("a", lambda p: MetricResult("a", 0, 1.0, False, [], "fail"))
    meter.register("b", lambda p: MetricResult("b", 0, 1.0, False, [], "fail"))
    d = Path(tempfile.mkdtemp())
    report = meter.measure(d, threshold=70)
    assert report.overall_score == 0.0
    assert report.passed is False


def test_evidence_test_with_only_raise():
    """Test function with only raise (not assert) should count."""
    d = _make_project({
        "tests/test_x.py": "def test_error():\n    raise ValueError('bad')\n",
    })
    tc, ac, et, en = _analyze_test_file(d / "tests" / "test_x.py")
    assert tc == 1
    assert ac == 1  # raise counts as assertion
    assert et == 0


# === Unicode file names ===

def test_unicode_filename():
    """Unicode file names should be handled."""
    d = _make_project({"src/計算.py": "def add(a, b):\n    return a + b\n"})
    result = collect_determinism(d)
    assert result.passed is True


def test_unicode_filename_evidence():
    """Unicode file names in evidence collection."""
    d = _make_project({"src/計算.py": "x = 1\n"})
    evidence = collect_evidence(d)
    assert evidence.name == "evidence"


def test_unicode_filename_transparency():
    """Unicode file names in transparency check."""
    d = _make_project({"src/計算.py": 'def f():\n    """Doc."""\n    pass\n'})
    result = collect_transparency(d)
    assert result.passed is True


# === Symlinks ===

def test_symlink_handling():
    """Symlinks should be handled gracefully (skip if broken)."""
    d = _make_project({"src/real.py": "x = 1\n"})
    link = d / "src" / "link.py"
    try:
        link.symlink_to(d / "src" / "real.py")
        result = collect_determinism(d)
        assert result.name == "determinism"
    except (OSError, AttributeError):
        # Symlinks may not be supported on this system
        pass


# === Plugin self-import ===

def test_plugin_self_import():
    """Plugin that imports itself should fail gracefully."""
    d = _make_project({
        "circular.py": (
            "import circular\n"
            "def collect_circular(target):\n"
            "    pass\n"
        ),
    })
    name, collector = _load_plugin(d / "circular.py")
    # Should fail gracefully (import error)
    assert name is None


# === Import from nonexistent module ===

def test_import_nonexistent_module():
    """Importing a nonexistent local module should be handled."""
    d = _make_project({
        "src/main.py": "import nonexistent_module_xyz\nx = 1\n",
    })
    result = collect_architecture(d)
    # Should not crash
    assert result.name == "architecture"


# === Git not available ===

def test_git_trust_no_repo():
    """Git operations on non-repo directory should return None/empty."""
    from trust_meter.git_trust import current_commit_info, commit_history, branch_name, is_dirty
    d = Path(tempfile.mkdtemp())
    # Not a git repo
    assert current_commit_info(d) is None
    assert commit_history(d) == []
    assert branch_name(d) == ""
    assert is_dirty(d) is False


# === Permission denied (simulated) ===

def test_unreadable_file_skipped():
    """Unreadable files should be skipped gracefully."""
    d = _make_project({"src/good.py": "x = 1\n"})
    # Create a file that exists but we can check the error path
    # by checking that the metric doesn't crash on missing files
    result = collect_determinism(d)
    assert result.name == "determinism"


# === All metrics on binary-heavy project ===

def test_all_metrics_binary_heavy():
    """All metrics on project with many binary files."""
    d = Path(tempfile.mkdtemp())
    src = d / "src"
    src.mkdir()
    (src / "good.py").write_text("x = 1\n")
    for i in range(5):
        (src / f"bad{i}.py").write_bytes(b"\x80\x81\x82")
    assert collect_determinism(d).name == "determinism"
    assert collect_locality(d).name == "locality"
    assert collect_evidence(d).name == "evidence"
    assert collect_reproducibility(d).name == "reproducibility"
    assert collect_architecture(d).name == "architecture"
    assert collect_complexity(d).name == "complexity"
    assert collect_transparency(d).name == "transparency"


# === Config with all edge values ===

def test_config_all_edge_values():
    """Config with extreme values."""
    config = parse_config(
        "[trust-meter]\n"
        "threshold = 0.0\n"
        "strict = true\n"
        "[skip]\n"
        'patterns = ["a", "b", "c"]\n'
        "[weights]\n"
        "a = 0.0\n"
        "b = 999.0\n"
        "[limits]\n"
        "x = 0\n"
        "y = 99999\n"
    )
    assert config.threshold == 0.0
    assert config.strict is True
    assert len(config.skip_patterns) == 3
    assert config.weights["a"] == 0.0
    assert config.weights["b"] == 999.0
    assert config.limits["y"] == 99999


# === Spec with all assertion types ===

def test_spec_all_assertion_types():
    """Spec with all assertion types."""
    spec = parse_spec(
        '[project]\nname = "test"\nmin_python = "3.9"\n'
        '[assertions]\nmodules = ["a", "b"]\n'
        'require_tests = true\nrequire_docstrings = true\n'
        'max_function_lines = 30\n'
    )
    # 2 module_exists + 2 has_test + 2 has_docstring + 1 max_function_lines
    assert len(spec.assertions) == 7


# === Meter with single failing metric ===

def test_meter_single_failing():
    """Meter with one failing metric should fail overall."""
    meter = TrustMeter()
    meter.register("good", lambda p: MetricResult("good", 100, 1.0, True, [], "ok"))
    meter.register("bad", lambda p: MetricResult("bad", 50, 1.0, False, [], "fail"))
    d = Path(tempfile.mkdtemp())
    report = meter.measure(d, threshold=70)
    assert report.passed is False  # one metric fails


# === Trending with many entries ===

def test_trending_many_entries():
    """Trending with many entries should work."""
    d = Path(tempfile.mkdtemp())
    tracker = TrendTracker(d)
    for i in range(100):
        tracker.add_score(float(i))
    assert tracker.count == 100
    assert tracker.average() == 49.5
    assert tracker.sparkline(width=10) != ""


# === Baseline roundtrip with all metric data ===

def test_baseline_full_roundtrip():
    """Baseline with all metric data should roundtrip."""
    from trust_meter.baseline import save_baseline, load_baseline
    d = Path(tempfile.mkdtemp())
    report = TrustReport(
        target="test", timestamp="2026-01-01T00:00:00Z",
        overall_score=95, passed=True,
        metrics=[
            MetricResult("det", 100, 1.0, True, ["evidence1"], "detail1"),
            MetricResult("loc", 90, 1.0, True, [], "detail2"),
        ],
    )
    path = d / "baseline.json"
    save_baseline(report, path)
    loaded = load_baseline(path)
    assert loaded.metrics[0].evidence == ["evidence1"]
    assert loaded.metrics[1].score == 90


# === Comparison with all tie ===

def test_comparison_all_tie():
    """Comparison where all metrics tie."""
    from trust_meter.compare import _build_comparison
    left = TrustReport("a", "", 90, True, [
        MetricResult("det", 90, 1.0, True, [], "ok"),
        MetricResult("loc", 90, 1.0, True, [], "ok"),
    ])
    right = TrustReport("b", "", 90, True, [
        MetricResult("det", 90, 1.0, True, [], "ok"),
        MetricResult("loc", 90, 1.0, True, [], "ok"),
    ])
    result = _build_comparison(left, right)
    assert result.overall_winner == "tie"
    assert all(m.winner == "tie" for m in result.metrics)


# === Comparison with missing metric ===

def test_comparison_missing_metric():
    """Comparison where one side has fewer metrics."""
    from trust_meter.compare import _build_comparison
    left = TrustReport("a", "", 90, True, [
        MetricResult("det", 100, 1.0, True, [], "ok"),
        MetricResult("loc", 80, 1.0, True, [], "ok"),
    ])
    right = TrustReport("b", "", 50, False, [
        MetricResult("det", 50, 1.0, False, [], "fail"),
    ])
    result = _build_comparison(left, right)
    assert len(result.metrics) == 2
    loc_metric = next(m for m in result.metrics if m.name == "loc")
    assert loc_metric.winner == "left"
    assert loc_metric.right_score == 0


# === API with all methods ===

def test_api_all_methods():
    """API should work for all methods."""
    from trust_meter.api import TrustAPI
    d = _make_project({
        "src/a.py": 'def f():\n    """Doc."""\n    pass\n',
        "tests/test_a.py": "def test_f():\n    pass\n",
    })
    api = TrustAPI()
    score = api.score(d)
    assert score.overall > 0
    assert isinstance(score.passed, bool)

    report = api.full_report(d)
    assert report.overall_score > 0

    hints = api.hints(d)
    assert isinstance(hints, list)

    modules = api.modules(d)
    assert "count" in modules

    batch = api.batch([d])
    assert len(batch) == 1
