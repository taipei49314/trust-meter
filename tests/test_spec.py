"""Tests for the spec engine."""

import tempfile
from pathlib import Path

from trust_meter.spec import (
    parse_spec, parse_spec_file, emit_assertions,
    verify_assertions, Assertion, Spec,
)


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_parse_spec_minimal():
    spec = parse_spec('[project]\nname = "test"\nmin_python = "3.9"')
    assert spec.name == "test"
    assert spec.min_python == "3.9"
    assert len(spec.assertions) == 0


def test_parse_spec_with_modules():
    spec = parse_spec(
        '[project]\nname = "test"\nmin_python = "3.9"\n'
        '[assertions]\nmodules = ["calc", "utils"]'
    )
    assert len(spec.assertions) == 2
    assert spec.assertions[0].kind == "module_exists"
    assert spec.assertions[0].target == "calc"


def test_parse_spec_with_tests_required():
    spec = parse_spec(
        '[project]\nname = "test"\nmin_python = "3.9"\n'
        '[assertions]\nmodules = ["calc"]\nrequire_tests = true'
    )
    kinds = [a.kind for a in spec.assertions]
    assert "module_exists" in kinds
    assert "has_test" in kinds


def test_parse_spec_with_docstrings_required():
    spec = parse_spec(
        '[project]\nname = "test"\nmin_python = "3.9"\n'
        '[assertions]\nmodules = ["calc"]\nrequire_docstrings = true'
    )
    kinds = [a.kind for a in spec.assertions]
    assert "has_docstring" in kinds


def test_parse_spec_with_max_function_lines():
    spec = parse_spec(
        '[project]\nname = "test"\nmin_python = "3.9"\n'
        '[assertions]\nmax_function_lines = 50'
    )
    assert any(a.kind == "max_function_lines" for a in spec.assertions)


def test_parse_spec_defaults():
    spec = parse_spec("")
    assert spec.name == "unnamed"
    assert spec.min_python == "3.9"


def test_parse_spec_file():
    d = _make_project({})
    spec_file = d / "spec.txt"
    spec_file.write_text('[project]\nname = "myproj"\nmin_python = "3.10"')
    spec = parse_spec_file(spec_file)
    assert spec.name == "myproj"
    assert spec.min_python == "3.10"


def test_emit_assertions():
    spec = parse_spec(
        '[project]\nname = "test"\nmin_python = "3.9"\n'
        '[assertions]\nmodules = ["calc"]\nrequire_tests = true'
    )
    assertions = emit_assertions(spec)
    assert len(assertions) == 2
    assert assertions[0].kind == "module_exists"
    assert assertions[1].kind == "has_test"


def test_verify_module_exists():
    d = _make_project({"src/calc.py": "def add(a, b):\n    return a + b\n"})
    assertions = [Assertion("module_exists", "calc", "true")]
    verified = verify_assertions(assertions, d)
    assert verified[0].evidence.startswith("found")
    assert verified[0].evidence.endswith("calc.py")


def test_verify_module_not_found():
    d = _make_project({})
    assertions = [Assertion("module_exists", "calc", "true")]
    verified = verify_assertions(assertions, d)
    assert verified[0].evidence == "not found"


def test_verify_has_test():
    d = _make_project({
        "src/calc.py": "def add(a, b):\n    return a + b\n",
        "tests/test_calc.py": "def test_add():\n    assert add(1, 2) == 3\n",
    })
    assertions = [Assertion("has_test", "calc", "true")]
    verified = verify_assertions(assertions, d)
    assert "test" in verified[0].evidence


def test_verify_has_test_missing():
    d = _make_project({"src/calc.py": "def add(a, b):\n    return a + b\n"})
    assertions = [Assertion("has_test", "calc", "true")]
    verified = verify_assertions(assertions, d)
    assert "no test" in verified[0].evidence


def test_verify_has_docstring():
    d = _make_project({
        "src/calc.py": 'def add(a, b):\n    """Add two numbers."""\n    return a + b\n',
    })
    assertions = [Assertion("has_docstring", "calc", "true")]
    verified = verify_assertions(assertions, d)
    assert verified[0].evidence == "documented"


def test_verify_has_docstring_missing():
    d = _make_project({
        "src/calc.py": "def add(a, b):\n    return a + b\n",
    })
    assertions = [Assertion("has_docstring", "calc", "true")]
    verified = verify_assertions(assertions, d)
    assert verified[0].evidence == "missing docstrings"


def test_verify_max_function_lines():
    d = _make_project({
        "src/calc.py": "def add(a, b):\n    return a + b\n",
    })
    assertions = [Assertion("max_function_lines", "*", "50")]
    verified = verify_assertions(assertions, d)
    assert verified[0].evidence == "all within limit"


def test_verify_max_function_lines_violation():
    lines = ["def big():\n"] + ["    x = 1\n"] * 60
    d = _make_project({"src/calc.py": "".join(lines)})
    assertions = [Assertion("max_function_lines", "*", "50")]
    verified = verify_assertions(assertions, d)
    assert "violation" in verified[0].evidence


def test_verify_unknown_assertion():
    d = _make_project({})
    assertions = [Assertion("unknown_type", "foo", "bar")]
    verified = verify_assertions(assertions, d)
    assert verified[0].evidence == "unknown assertion type"


def test_spec_to_dict():
    spec = parse_spec(
        '[project]\nname = "test"\nmin_python = "3.9"\n'
        '[assertions]\nmodules = ["calc"]'
    )
    d = spec.to_dict()
    assert d["name"] == "test"
    assert len(d["assertions"]) == 1


def test_full_spec_workflow():
    """End-to-end: parse spec, emit assertions, verify against project."""
    d = _make_project({
        "src/calc.py": 'def add(a, b):\n    """Add."""\n    return a + b\n',
        "tests/test_calc.py": "def test_add():\n    assert add(1, 2) == 3\n",
    })
    spec = parse_spec(
        '[project]\nname = "test"\nmin_python = "3.9"\n'
        '[assertions]\nmodules = ["calc"]\nrequire_tests = true\nrequire_docstrings = true'
    )
    assertions = emit_assertions(spec)
    verified = verify_assertions(assertions, d)

    # All should pass
    for v in verified:
        assert "not found" not in v.evidence
        assert "no test" not in v.evidence
        assert "missing" not in v.evidence
