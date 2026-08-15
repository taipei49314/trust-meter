"""Tests for the config module."""

import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from trust_meter.config import (
    Config, ConfigError, MAX_CONFIG_BYTES, find_config, load_config,
    load_config_exact, parse_config, parse_config_strict,
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


def test_parse_config_strict_accepts_core_effective_bounded_subset():
    config = parse_config_strict(
        '[trust-meter]\n'
        'threshold = 80.5\n'
        'phase_gate = "preflight"\n'
        'strict = true\n'
    )
    assert config.threshold == 80.5
    assert config.phase_gate == "preflight"
    assert config.strict is True


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[unknown]\nvalue = 1\n', "line 1: unknown section [unknown]"),
        (
            '[trust-meter]\nunknown = 1\n',
            "line 2: unknown key [trust-meter].unknown",
        ),
        ('[weights]\ncustom_plugin = 1\n', "line 1: unknown section [weights]"),
        ('[limits]\nunknown_limit = 1\n', "line 1: unknown section [limits]"),
        ('threshold = 75\n', "line 1: key appears before a section"),
        (
            '[trust-meter]\nthis is not an assignment\n',
            "line 2: malformed assignment",
        ),
        ('[trust-meter]\nthreshold = NaN\n', "line 2: expected a decimal number"),
        ('[trust-meter]\nthreshold = inf\n', "line 2: expected a decimal number"),
        (
            '[trust-meter]\nthreshold = 101\n',
            "line 2: number must be finite and between 0 and 100",
        ),
        ('[trust-meter]\nstrict = yes\n', "line 2: boolean must be true or false"),
        ('[skip]\npatterns = [vendor/*]\n', "line 1: unknown section [skip]"),
        ('[trust-meter]\nthreshold = 75,\n', "line 2: expected a decimal number"),
        (
            '[trust-meter]\u2028threshold = 75\n',
            "config contains non-ASCII whitespace or a Unicode category C character",
        ),
        (
            '[trust-meter]\nthreshold\u00a0= 75\n',
            "config contains non-ASCII whitespace or a Unicode category C character",
        ),
        *[
            (
                f'[trust-meter]\nphase_gate = "pre{character}flight"\n',
                "config contains non-ASCII whitespace or a Unicode category C character",
            )
            for character in (
                "\u00a0",
                "\u0085",
                "\u200b",
                "\u202e",
                "\ud800",
                "\ue000",
                "\u0378",
            )
        ],
    ],
)
def test_parse_config_strict_rejects_unknown_malformed_and_nonfinite(text, message):
    with pytest.raises(ConfigError) as error:
        parse_config_strict(text)
    assert str(error.value) == message


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            '[trust-meter]\nthreshold = 70\nthreshold = 80\n',
            "line 3: duplicate key [trust-meter].threshold",
        ),
        (
            '[trust-meter]\nthreshold = 70\n[trust-meter]\nstrict = true\n',
            "line 3: duplicate section [trust-meter]",
        ),
    ],
)
def test_parse_config_strict_rejects_duplicate_keys_and_sections(text, message):
    with pytest.raises(ConfigError) as error:
        parse_config_strict(text)
    assert str(error.value) == message


def test_parse_config_strict_allows_full_line_comments_but_not_inline_comments():
    config = parse_config_strict(
        "# admitted full-line comment\n[trust-meter]\nthreshold = 75\n"
    )
    assert config.threshold == 75.0

    with pytest.raises(ConfigError) as error:
        parse_config_strict("[trust-meter]\nthreshold = 75 # not admitted\n")
    assert str(error.value) == "line 2: expected a decimal number"


def test_load_config_exact_hashes_the_bytes_it_parses(tmp_path):
    config_path = tmp_path / "chosen.toml"
    raw = b'[trust-meter]\nthreshold = 82\nphase_gate = "release"\n'
    config_path.write_bytes(raw)

    exact = load_config_exact(config_path)

    assert exact.config.threshold == 82.0
    assert exact.config.phase_gate == "release"
    assert exact.sha256 == hashlib.sha256(raw).hexdigest()
    assert exact.byte_length == len(raw)


def test_load_config_exact_rejects_lstat_open_identity_swap(tmp_path, monkeypatch):
    config_path = tmp_path / "chosen.toml"
    config_path.write_text("[trust-meter]\nthreshold = 82\n", encoding="utf-8")
    real_lstat = Path.lstat
    inspected = False

    def swapped_first_lstat(path):
        nonlocal inspected
        info = real_lstat(path)
        if path != config_path or inspected:
            return info
        inspected = True
        return SimpleNamespace(
            st_dev=info.st_dev,
            st_ino=info.st_ino + 1,
            st_mode=info.st_mode,
            st_size=info.st_size,
            st_mtime=info.st_mtime,
            st_mtime_ns=info.st_mtime_ns,
            st_file_attributes=getattr(info, "st_file_attributes", 0),
        )

    monkeypatch.setattr(Path, "lstat", swapped_first_lstat)
    with pytest.raises(ConfigError) as error:
        load_config_exact(config_path)
    assert str(error.value) == "config file changed before it was opened"


def test_load_config_exact_core_profile_rejects_unapplied_sections(tmp_path):
    config_path = tmp_path / "unsupported.toml"
    config_path.write_text('[skip]\npatterns = ["vendor/*"]\n', encoding="utf-8")
    with pytest.raises(ConfigError) as error:
        load_config_exact(config_path)
    assert str(error.value) == "line 1: unknown section [skip]"


def test_load_config_exact_missing_is_an_error(tmp_path):
    missing = tmp_path / "missing.toml"
    with pytest.raises(ConfigError) as error:
        load_config_exact(missing)
    assert str(error.value) == f"config file does not exist: {missing}"


def test_load_config_exact_requires_strict_utf8(tmp_path):
    config_path = tmp_path / "bad.toml"
    config_path.write_bytes(b"[trust-meter]\nphase_gate = \"\xff\"\n")
    with pytest.raises(ConfigError) as error:
        load_config_exact(config_path)
    assert str(error.value) == "config file is not strict UTF-8"


def test_load_config_exact_is_size_bounded(tmp_path):
    config_path = tmp_path / "huge.toml"
    config_path.write_bytes(b"#" * (MAX_CONFIG_BYTES + 1))
    with pytest.raises(ConfigError) as error:
        load_config_exact(config_path)
    assert str(error.value) == f"config exceeds {MAX_CONFIG_BYTES} bytes"


def test_load_config_exact_rejects_symlink(tmp_path):
    config_path = tmp_path / "real.toml"
    config_path.write_text("[trust-meter]\nthreshold = 75\n", encoding="utf-8")
    link = tmp_path / "linked.toml"
    try:
        link.symlink_to(config_path)
    except OSError:
        pytest.skip("symlink creation is not available")
    with pytest.raises(ConfigError) as error:
        load_config_exact(link)
    assert str(error.value) == "config file must not be a symlink or reparse point"
