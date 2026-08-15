"""Tests for the CLI entry point."""

import hashlib
import json
import re
import tempfile
from pathlib import Path

import pytest

from trust_meter import __version__
from trust_meter.cli import (
    JSON_V1_SCHEMA_VERSION,
    _canonical_json_v1_bytes,
    _json_v1_payload,
    build_meter,
    main,
)


def test_build_meter():
    meter = build_meter()
    assert len(meter._collectors) >= 5


def test_main_clean_project():
    d = Path(tempfile.mkdtemp())
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text(
        'def add(a, b):\n'
        '    """Add two numbers."""\n'
        '    return a + b\n'
    )
    (d / "tests").mkdir()
    (d / "tests" / "test_main.py").write_text(
        'def test_add():\n'
        '    assert add(1, 2) == 3\n'
    )
    # Should not raise
    result = main([str(d)])
    assert result == 0


def test_main_with_json_output():
    d = Path(tempfile.mkdtemp())
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text('x = 1\n')
    result = main([str(d), "--json"])
    assert result == 1  # no test for main


def test_main_with_phase():
    d = Path(tempfile.mkdtemp())
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text('x = 1\n')
    result = main([str(d), "--phase", "Phase 0"])
    assert result == 1


def test_main_nonexistent_dir():
    result = main(["/nonexistent/path/that/does/not/exist"])
    assert result == 1


def test_main_strict_mode():
    d = Path(tempfile.mkdtemp())
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text('x = 1\n')
    result = main([str(d), "--strict"])
    assert result == 1  # no tests = evidence fails


def test_main_output_file():
    d = Path(tempfile.mkdtemp())
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text('x = 1\n')
    out = d / "report.md"
    result = main([str(d), "--output", str(out)])
    assert out.exists()
    content = out.read_text()
    assert "Trust Report" in content


def test_no_config_does_not_call_legacy_discovery(tmp_path, monkeypatch):
    def unexpected_discovery(_target):
        raise AssertionError("legacy config discovery was called")

    monkeypatch.setattr("trust_meter.cli.load_config", unexpected_discovery)
    assert main([str(tmp_path), "--no-config", "--threshold", "0"]) == 0


def test_legacy_default_still_discovers_ancestor_config(tmp_path):
    (tmp_path / ".trust-meter.toml").write_text(
        "[trust-meter]\nthreshold = 101\n", encoding="utf-8"
    )
    target = tmp_path / "subject"
    target.mkdir()
    assert main([str(target)]) == 1


def test_config_and_no_config_are_mutually_exclusive(tmp_path):
    config_path = tmp_path / "chosen.toml"
    config_path.write_text("[trust-meter]\nthreshold = 75\n", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main([str(tmp_path), "--no-config", "--config", str(config_path)])
    assert error.value.code == 2


def test_json_v1_requires_an_explicit_config_boundary(tmp_path):
    with pytest.raises(SystemExit) as error:
        main([str(tmp_path), "--json-v1"])
    assert error.value.code == 2


@pytest.mark.parametrize("legacy_flag", ["--json", "--junit", "--html"])
def test_json_v1_rejects_legacy_output_flags(tmp_path, legacy_flag):
    with pytest.raises(SystemExit) as error:
        main([str(tmp_path), "--json-v1", "--no-config", legacy_flag])
    assert error.value.code == 2


def test_json_v1_rejects_output_file(tmp_path):
    with pytest.raises(SystemExit) as error:
        main([
            str(tmp_path), "--json-v1", "--no-config",
            "--output", str(tmp_path / "result.json"),
        ])
    assert error.value.code == 2
    assert not (tmp_path / "result.json").exists()


def test_version_is_available_without_a_target(capsys):
    with pytest.raises(SystemExit) as error:
        main(["--version"])
    assert error.value.code == 0
    assert capsys.readouterr().out == f"trust-meter {__version__}\n"


def test_runtime_version_matches_package_metadata():
    pyproject = (
        Path(__file__).resolve().parents[1] / "pyproject.toml"
    ).read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    assert match is not None
    assert match.group(1) == __version__


def test_json_v1_is_closed_and_omits_clock_and_target_path(tmp_path, capsysbinary):
    result = main([
        str(tmp_path), "--json-v1", "--no-config", "--threshold", "0",
        "--phase", "preflight",
    ])
    captured = capsysbinary.readouterr()
    payload = json.loads(captured.out)

    assert result == 0
    assert captured.err == b""
    assert captured.out.endswith(b"\n")
    assert captured.out.count(b"\n") == 1
    assert b": " not in captured.out
    assert payload["schema_version"] == JSON_V1_SCHEMA_VERSION
    assert payload["tool"] == {"name": "trust-meter", "version": __version__}
    assert payload["profile"]["collector_plugin_loading"] == "disabled"
    assert payload["profile"]["collector_target_test_execution"] == "disabled"
    assert payload["profile"]["collector_target_module_loading"] == "disabled"
    assert payload["authority_effect"] == "none"
    assert "timestamp" not in payload
    assert "target" not in payload
    assert str(tmp_path).encode("utf-8") not in captured.out


def test_json_v1_exact_config_reports_digest_not_path(tmp_path, capsysbinary):
    target = tmp_path / "subject"
    target.mkdir()
    config_path = tmp_path / "private-name.toml"
    raw = b'[trust-meter]\nthreshold = 0\nphase_gate = "bound"\n'
    config_path.write_bytes(raw)

    assert main([str(target), "--json-v1", "--config", str(config_path)]) == 0
    captured = capsysbinary.readouterr()
    payload = json.loads(captured.out)

    assert payload["configuration"]["mode"] == "exact_file"
    assert payload["configuration"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert payload["configuration"]["byte_length"] == len(raw)
    assert str(config_path).encode("utf-8") not in captured.out


@pytest.mark.parametrize(
    "content",
    [
        "[trust-meter]\nthreshold = NaN\n",
        "[trust-meter]\nthreshold = 75\nthreshold = 80\n",
        "[trust-meter]\nunknown = true\n",
        "[trust-meter]\nnot an assignment\n",
        "[skip]\npatterns = []\n",
    ],
)
def test_json_v1_invalid_exact_config_exits_two(tmp_path, content, capsys):
    target = tmp_path / "subject"
    target.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(content, encoding="utf-8")

    assert main([str(target), "--json-v1", "--config", str(config_path)]) == 2
    assert "Error:" in capsys.readouterr().err


def test_json_v1_missing_exact_config_exits_two(tmp_path, capsys):
    (tmp_path / ".trust-meter.toml").write_text(
        "[trust-meter]\nthreshold = 0\n", encoding="utf-8"
    )
    assert main([
        str(tmp_path), "--json-v1", "--config", str(tmp_path / "missing.toml")
    ]) == 2
    assert "does not exist" in capsys.readouterr().err


@pytest.mark.parametrize("threshold", ["nan", "inf", "-1", "101"])
def test_json_v1_rejects_nonfinite_or_out_of_range_cli_threshold(
    tmp_path, threshold, capsys
):
    assert main([
        str(tmp_path), "--json-v1", "--no-config", "--threshold", threshold,
    ]) == 2
    assert "machine threshold" in capsys.readouterr().err


@pytest.mark.parametrize(
    "phase_gate",
    [
        "pre\u00a0flight",
        "pre\u0085flight",
        "pre\u200bflight",
        "pre\u202eflight",
        "pre\ud800flight",
        "pre\ue000flight",
        "pre\u0378flight",
    ],
)
def test_json_v1_direct_phase_rejects_non_ascii_whitespace_and_category_c(
    tmp_path, phase_gate, capsys
):
    assert main([
        str(tmp_path), "--json-v1", "--no-config", "--phase", phase_gate,
    ]) == 2
    assert "machine phase gate is invalid" in capsys.readouterr().err


def test_builtin_profile_does_not_execute_plugins_conftest_or_target_code(
    tmp_path, capsysbinary
):
    marker = tmp_path / "executed"
    payload = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
    )
    plugin = tmp_path / ".trust-meter" / "plugins" / "malicious.py"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(payload, encoding="utf-8")
    (tmp_path / "conftest.py").write_text(payload, encoding="utf-8")
    (tmp_path / "target_module.py").write_text(payload, encoding="utf-8")

    assert main([str(tmp_path), "--json-v1", "--no-config", "--threshold", "0"]) == 0
    captured = capsysbinary.readouterr()

    result = json.loads(captured.out)
    assert result["profile"]["name"] == "builtin-static-v1"
    assert result["result"]["threshold_met"] is True
    assert result["result"]["all_metrics_passed"] is False
    assert result["result"]["advisory_gate_met"] is True
    assert not marker.exists()

    assert main([
        str(tmp_path), "--json-v1", "--no-config", "--threshold", "0", "--strict",
    ]) == 1
    strict_result = json.loads(capsysbinary.readouterr().out)
    assert strict_result["result"]["advisory_gate_met"] is False
    assert not marker.exists()


def test_json_v1_bytes_are_independent_of_timestamp_and_target_path(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for target in (first, second):
        (target / "src").mkdir(parents=True)
        (target / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")

    meter = build_meter()
    first_report = meter.measure(first, threshold=0, phase_gate="preflight")
    second_report = meter.measure(second, threshold=0, phase_gate="preflight")
    first_report.timestamp = "2000-01-01T00:00:00Z"
    second_report.timestamp = "2099-12-31T23:59:59Z"

    first_bytes = _canonical_json_v1_bytes(_json_v1_payload(
        first_report,
        threshold=0,
        phase_gate="preflight",
        strict=False,
        config_mode="none",
        config_sha256=None,
        config_byte_length=0,
    ))
    second_bytes = _canonical_json_v1_bytes(_json_v1_payload(
        second_report,
        threshold=0,
        phase_gate="preflight",
        strict=False,
        config_mode="none",
        config_sha256=None,
        config_byte_length=0,
    ))

    assert first_bytes == second_bytes


@pytest.mark.parametrize(
    ("raw_score", "emitted_score", "threshold_met"),
    [(74.996, 75.0, True), (74.994, 74.99, False)],
)
def test_json_v1_threshold_uses_the_emitted_rounded_score(
    tmp_path, raw_score, emitted_score, threshold_met
):
    report = build_meter().measure(tmp_path, threshold=75)
    report.overall_score = raw_score
    payload = _json_v1_payload(
        report,
        threshold=75,
        phase_gate="preflight",
        strict=False,
        config_mode="none",
        config_sha256=None,
        config_byte_length=0,
    )

    assert payload["result"]["overall_score"] == emitted_score
    assert payload["result"]["threshold_met"] is threshold_met
    assert payload["result"]["advisory_gate_met"] is threshold_met


def test_json_v1_schema_is_closed_and_matches_emitted_payload(tmp_path):
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "schemas"
        / "trust-meter-measure-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "schema_version", "tool", "profile", "configuration", "result", "authority_effect",
    }
    assert "timestamp" not in schema["properties"]
    assert "target" not in schema["properties"]
    assert (
        schema["properties"]["configuration"]["properties"]["phase_gate"]["pattern"]
        == r"^(?: |[^\s\p{C}])*$"
    )

    report = build_meter().measure(tmp_path, threshold=0, phase_gate="preflight")
    payload = _json_v1_payload(
        report,
        threshold=0,
        phase_gate="preflight",
        strict=False,
        config_mode="none",
        config_sha256=None,
        config_byte_length=0,
    )
    metrics_schema = schema["properties"]["result"]["properties"]["metrics"]
    slots = metrics_schema["prefixItems"]
    schema_contract = [
        (
            slot["allOf"][1]["properties"]["name"]["const"],
            slot["allOf"][1]["properties"]["weight"]["const"],
        )
        for slot in slots
    ]
    payload_contract = [
        (metric["name"], metric["weight"])
        for metric in payload["result"]["metrics"]
    ]

    assert metrics_schema["items"] is False
    assert len(slots) == metrics_schema["minItems"] == metrics_schema["maxItems"] == 7
    assert schema_contract == payload_contract == [
        ("determinism", 1.0),
        ("locality", 1.0),
        ("evidence", 1.0),
        ("reproducibility", 1.0),
        ("architecture", 1.0),
        ("complexity", 0.5),
        ("transparency", 0.5),
    ]
