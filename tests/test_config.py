"""Tests for the config module."""

import tempfile
from pathlib import Path

from trust_meter.config import (
    parse_config, find_config, load_config, Config,
)


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_parse_empty():
    config = parse_config("")
    assert config.threshold == 70.0
    assert config.phase_gate == ""
    assert config.strict is False


def test_parse_threshold():
    config = parse_config('[trust-meter]\nthreshold = 85.0')
    assert config.threshold == 85.0


def test_parse_phase_gate():
    config = parse_config('[trust-meter]\nphase_gate = "Phase 1"')
    assert config.phase_gate == "Phase 1"


def test_parse_strict():
    config = parse_config('[trust-meter]\nstrict = true')
    assert config.strict is True


def test_parse_skip_patterns():
    config = parse_config('[skip]\npatterns = ["vendor/*", "generated/*"]')
    assert config.skip_patterns == ["vendor/*", "generated/*"]


def test_parse_weights():
    config = parse_config('[weights]\ndeterminism = 2.0\nlocality = 0.5')
    assert config.weights["determinism"] == 2.0
    assert config.weights["locality"] == 0.5


def test_parse_limits():
    config = parse_config('[limits]\nmax_function_lines = 30\nmax_imports_per_module = 10')
    assert config.limits["max_function_lines"] == 30
    assert config.limits["max_imports_per_module"] == 10


def test_parse_full_config():
    text = (
        '[trust-meter]\n'
        'threshold = 80.0\n'
        'phase_gate = "Phase 2"\n'
        'strict = true\n'
        '\n'
        '[skip]\n'
        'patterns = ["vendor/*"]\n'
        '\n'
        '[weights]\n'
        'determinism = 1.5\n'
        '\n'
        '[limits]\n'
        'max_function_lines = 40\n'
    )
    config = parse_config(text)
    assert config.threshold == 80.0
    assert config.phase_gate == "Phase 2"
    assert config.strict is True
    assert config.skip_patterns == ["vendor/*"]
    assert config.weights["determinism"] == 1.5
    assert config.limits["max_function_lines"] == 40


def test_parse_comments():
    text = '# This is a comment\n[trust-meter]\n# Another comment\nthreshold = 90.0'
    config = parse_config(text)
    assert config.threshold == 90.0


def test_parse_invalid_values():
    config = parse_config('[trust-meter]\nthreshold = abc\nstrict = maybe')
    assert config.threshold == 70.0  # default
    assert config.strict is False  # default


def test_config_get_weight():
    config = Config()
    assert config.get_weight("determinism", 1.0) == 1.0
    config.weights["determinism"] = 2.0
    assert config.get_weight("determinism", 1.0) == 2.0


def test_config_get_limit():
    config = Config()
    assert config.get_limit("max_function_lines", 50) == 50
    config.limits["max_function_lines"] = 30
    assert config.get_limit("max_function_lines", 50) == 30


def test_find_config():
    d = _make_project({
        ".trust-meter.toml": '[trust-meter]\nthreshold = 80.0',
        "src/main.py": "x = 1\n",
    })
    config_path = find_config(d / "src")
    assert config_path is not None
    assert config_path.name == ".trust-meter.toml"


def test_find_config_not_found():
    d = _make_project({"src/main.py": "x = 1\n"})
    config_path = find_config(d)
    assert config_path is None


def test_load_config():
    d = _make_project({
        ".trust-meter.toml": '[trust-meter]\nthreshold = 85.0',
    })
    config = load_config(d)
    assert config.threshold == 85.0


def test_load_config_no_file():
    d = _make_project({})
    config = load_config(d)
    assert config.threshold == 70.0  # default


def test_find_config_walks_up():
    d = _make_project({
        ".trust-meter.toml": '[trust-meter]\nthreshold = 75.0',
        "src/deep/main.py": "x = 1\n",
    })
    config_path = find_config(d / "src" / "deep")
    assert config_path is not None
    config = parse_config(config_path.read_text())
    assert config.threshold == 75.0
