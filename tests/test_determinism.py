"""Tests for the AST-based determinism metric."""

import tempfile
from pathlib import Path

from trust_meter.metrics.determinism import collect_determinism


def _make_project(files: dict[str, str]) -> Path:
    """Create a temp project with given files."""
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_clean_project():
    d = _make_project({
        "src/main.py": "def add(a, b):\n    return a + b\n",
        "src/utils.py": "def double(x):\n    return x * 2\n",
    })
    result = collect_determinism(d)
    assert result.score == 100.0
    assert result.passed is True
    assert result.name == "determinism"


def test_random_usage():
    d = _make_project({
        "src/main.py": "import random\nvalue = random.randint(1, 10)\n",
    })
    result = collect_determinism(d)
    assert result.score < 100.0
    assert result.passed is False
    assert any("random" in e for e in result.evidence)


def test_requests_usage():
    d = _make_project({
        "src/main.py": "import requests\nresp = requests.get('http://example.com')\n",
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert any("network" in e for e in result.evidence)


def test_comment_not_flagged():
    d = _make_project({
        "src/main.py": "# random.randint is not called\nx = 1\n",
    })
    result = collect_determinism(d)
    assert result.passed is True


def test_string_not_flagged():
    """AST analysis should NOT flag random.randint inside strings."""
    d = _make_project({
        "src/main.py": 'msg = "random.randint is dangerous"\nx = 1\n',
    })
    result = collect_determinism(d)
    assert result.passed is True


def test_pattern_definition_not_flagged():
    """Pattern definition lines should not trigger violations."""
    d = _make_project({
        "src/main.py": (
            'PATTERNS = [\n'
            '    (r"\\brandom\\.(randint|random)\\b", "random"),\n'
            ']\n'
        ),
    })
    result = collect_determinism(d)
    assert result.passed is True


def test_test_files_skipped():
    d = _make_project({
        "tests/test_main.py": "import random\nvalue = random.randint(1, 10)\n",
        "src/main.py": "x = 1\n",
    })
    result = collect_determinism(d)
    assert result.passed is True


def test_empty_project():
    d = _make_project({})
    result = collect_determinism(d)
    assert result.score == 100.0
    assert result.passed is True


def test_dynamic_import():
    d = _make_project({
        "src/main.py": "mod = __import__('os')\n",
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert any("dynamic_import" in e for e in result.evidence)


def test_multiple_violations():
    d = _make_project({
        "src/main.py": (
            "import random\n"
            "import requests\n"
            "value = random.randint(1, 10)\n"
            "resp = requests.get('http://example.com')\n"
        ),
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert result.score < 100.0
    assert len(result.evidence) >= 2


# AST-specific tests

def test_aliased_import():
    """import random as r; r.randint() should be caught."""
    d = _make_project({
        "src/main.py": "import random as r\nvalue = r.randint(1, 10)\n",
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert any("random" in e for e in result.evidence)


def test_from_import():
    """from random import randint; randint() should be caught."""
    d = _make_project({
        "src/main.py": "from random import randint\nvalue = randint(1, 10)\n",
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert any("random" in e for e in result.evidence)


def test_from_import_alias():
    """from random import choice as pick; pick() should be caught."""
    d = _make_project({
        "src/main.py": "from random import choice as pick\nvalue = pick([1, 2, 3])\n",
    })
    result = collect_determinism(d)
    assert result.passed is False


def test_chained_attribute():
    """urllib.request.urlopen() should be caught."""
    d = _make_project({
        "src/main.py": "import urllib.request\nresp = urllib.request.urlopen('http://example.com')\n",
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert any("network" in e for e in result.evidence)


def test_time_time():
    """time.time() should be caught."""
    d = _make_project({
        "src/main.py": "import time\nnow = time.time()\n",
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert any("timestamp" in e for e in result.evidence)


def test_datetime_now():
    """datetime.now() should be caught."""
    d = _make_project({
        "src/main.py": "from datetime import datetime\nnow = datetime.now()\n",
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert any("timestamp" in e for e in result.evidence)


def test_os_urandom():
    """os.urandom() should be caught."""
    d = _make_project({
        "src/main.py": "import os\ndata = os.urandom(32)\n",
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert any("entropy" in e for e in result.evidence)


def test_secrets_usage():
    """secrets.token_hex() should be caught."""
    d = _make_project({
        "src/main.py": "import secrets\ntoken = secrets.token_hex(16)\n",
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert any("entropy" in e for e in result.evidence)


def test_importlib_import_module():
    """importlib.import_module() should be caught."""
    d = _make_project({
        "src/main.py": "import importlib\nmod = importlib.import_module('os')\n",
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert any("dynamic_import" in e for e in result.evidence)


def test_socket_connect():
    """socket.connect() should be caught."""
    d = _make_project({
        "src/main.py": "import socket\ns = socket.socket()\ns.connect(('localhost', 80))\n",
    })
    result = collect_determinism(d)
    assert result.passed is False
    assert any("network" in e for e in result.evidence)


def test_no_false_positive_on_local_function():
    """A local function named 'random' should not be flagged."""
    d = _make_project({
        "src/main.py": "def random():\n    return 42\nvalue = random()\n",
    })
    result = collect_determinism(d)
    assert result.passed is True


def test_syntax_error_graceful():
    """Files with syntax errors should be skipped gracefully."""
    d = _make_project({
        "src/main.py": "def broken(\n    pass\n",
    })
    result = collect_determinism(d)
    # Should not crash, just skip the file
    assert result.name == "determinism"
