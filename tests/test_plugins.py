"""Tests for the plugin system."""

import tempfile
from pathlib import Path

from trust_meter.plugins import discover_plugins, _load_plugin, validate_plugin
from trust_meter.meter import MetricResult


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_discover_plugins():
    d = _make_project({
        ".trust-meter/plugins/my_check.py": (
            "from trust_meter.meter import MetricResult\n"
            "def collect_my_check(target):\n"
            "    return MetricResult('my_check', 100, 1.0, True, [], 'ok')\n"
        ),
    })
    plugins = discover_plugins(d)
    assert "my_check" in plugins
    assert callable(plugins["my_check"])


def test_discover_plugins_none():
    d = _make_project({})
    plugins = discover_plugins(d)
    assert len(plugins) == 0


def test_discover_plugins_skips_underscore():
    d = _make_project({
        ".trust-meter/plugins/_private.py": (
            "def collect_private(target):\n"
            "    pass\n"
        ),
        ".trust-meter/plugins/public.py": (
            "from trust_meter.meter import MetricResult\n"
            "def collect_public(target):\n"
            "    return MetricResult('public', 100, 1.0, True, [], 'ok')\n"
        ),
    })
    plugins = discover_plugins(d)
    assert "public" in plugins
    assert "_private" not in plugins


def test_discover_plugins_walks_up():
    d = _make_project({
        ".trust-meter/plugins/root_check.py": (
            "from trust_meter.meter import MetricResult\n"
            "def collect_root_check(target):\n"
            "    return MetricResult('root_check', 100, 1.0, True, [], 'ok')\n"
        ),
        "src/deep/main.py": "x = 1\n",
    })
    plugins = discover_plugins(d / "src" / "deep")
    assert "root_check" in plugins


def test_load_plugin():
    d = _make_project({
        "my_metric.py": (
            "from trust_meter.meter import MetricResult\n"
            "def collect_my_metric(target):\n"
            "    return MetricResult('my_metric', 95, 1.0, True, [], 'good')\n"
        ),
    })
    name, collector = _load_plugin(d / "my_metric.py")
    assert name == "my_metric"
    assert collector is not None
    result = collector(d)
    assert isinstance(result, MetricResult)
    assert result.score == 95


def test_load_plugin_no_collector():
    d = _make_project({
        "no_func.py": "x = 1\n",
    })
    name, collector = _load_plugin(d / "no_func.py")
    assert name is None
    assert collector is None


def test_load_plugin_syntax_error():
    d = _make_project({
        "broken.py": "def broken(\n    pass\n",
    })
    name, collector = _load_plugin(d / "broken.py")
    assert name is None
    assert collector is None


def test_validate_plugin_valid():
    def my_collector(target):
        return MetricResult("test", 100, 1.0, True, [], "ok")

    valid, msg = validate_plugin(my_collector, "test")
    assert valid is True
    assert msg == ""


def test_validate_plugin_wrong_return():
    def bad_collector(target):
        return "not a MetricResult"

    valid, msg = validate_plugin(bad_collector, "bad")
    assert valid is False
    assert "MetricResult" in msg


def test_validate_plugin_no_args():
    def no_args():
        return MetricResult("test", 100, 1.0, True, [], "ok")

    valid, msg = validate_plugin(no_args, "no_args")
    assert valid is False
    assert "argument" in msg


def test_plugin_integration_with_meter():
    """Plugin should be registerable and usable with TrustMeter."""
    from trust_meter.meter import TrustMeter

    d = _make_project({
        ".trust-meter/plugins/custom.py": (
            "from trust_meter.meter import MetricResult\n"
            "def collect_custom(target):\n"
            "    return MetricResult('custom', 88, 1.0, True, [], 'custom check')\n"
        ),
        "src/main.py": "x = 1\n",
    })

    plugins = discover_plugins(d)
    meter = TrustMeter()
    for name, collector in plugins.items():
        meter.register(name, collector, weight=1.0)

    report = meter.measure(d, threshold=70)
    custom_metric = next((m for m in report.metrics if m.name == "custom"), None)
    assert custom_metric is not None
    assert custom_metric.score == 88


def test_multiple_plugins():
    d = _make_project({
        ".trust-meter/plugins/check_a.py": (
            "from trust_meter.meter import MetricResult\n"
            "def collect_check_a(target):\n"
            "    return MetricResult('check_a', 90, 1.0, True, [], 'a')\n"
        ),
        ".trust-meter/plugins/check_b.py": (
            "from trust_meter.meter import MetricResult\n"
            "def collect_check_b(target):\n"
            "    return MetricResult('check_b', 80, 1.0, True, [], 'b')\n"
        ),
    })
    plugins = discover_plugins(d)
    assert len(plugins) == 2
    assert "check_a" in plugins
    assert "check_b" in plugins
