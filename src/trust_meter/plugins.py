"""Plugin system: load custom metrics without modifying core code.

Plugins are Python files that define a `collect_<name>(target: Path) -> MetricResult`
function. They are auto-discovered from `.trust-meter/plugins/` directories.

Usage:
    # Auto-discover and register plugins
    plugins = discover_plugins(Path("."))
    for name, collector in plugins.items():
        meter.register(name, collector, weight=1.0)

Plugin file example (.trust-meter/plugins/my_metric.py):
    from trust_meter.meter import MetricResult

    def collect_my_metric(target):
        # Your custom analysis here
        return MetricResult(
            name="my_metric",
            score=100.0,
            weight=1.0,
            passed=True,
            evidence=[],
            details="All good",
        )
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from trust_meter.meter import MetricResult

PLUGIN_DIR_NAME = ".trust-meter"
PLUGIN_SUBDIR = "plugins"


def discover_plugins(root: Path) -> dict[str, callable]:
    """Discover plugin collectors from .trust-meter/plugins/ directories.

    Returns dict of {metric_name: collector_function}.
    Walks up from root looking for plugin directories.
    """
    plugins: dict[str, callable] = {}
    plugin_dirs = _find_plugin_dirs(root)

    for plugin_dir in plugin_dirs:
        for py_file in sorted(plugin_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            name, collector = _load_plugin(py_file)
            if name and collector:
                plugins[name] = collector

    return plugins


def _find_plugin_dirs(root: Path) -> list[Path]:
    """Find all .trust-meter/plugins/ directories from root upward."""
    dirs: list[Path] = []
    current = root.resolve()
    while True:
        plugin_dir = current / PLUGIN_DIR_NAME / PLUGIN_SUBDIR
        if plugin_dir.is_dir():
            dirs.append(plugin_dir)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return dirs


def _load_plugin(path: Path) -> tuple[str, callable | None]:
    """Load a plugin file and extract its collector function.

    Returns (name, collector_function) or (None, None) on failure.
    """
    try:
        # Create a module name from the file
        module_name = f"trust_meter_plugin_{path.stem}"

        # Load the module
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return (None, None)

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Find the collector function
        collector_name = f"collect_{path.stem}"
        collector = getattr(module, collector_name, None)

        if collector is None:
            # Try any function starting with collect_
            for attr_name in dir(module):
                if attr_name.startswith("collect_"):
                    collector = getattr(module, attr_name)
                    break

        if collector and callable(collector):
            return (path.stem, collector)

        return (None, None)
    except Exception:
        return (None, None)


def validate_plugin(collector: callable, name: str) -> tuple[bool, str]:
    """Validate that a plugin collector has the right signature.

    Returns (valid, error_message).
    """
    import inspect

    sig = inspect.signature(collector)
    params = list(sig.parameters.keys())

    # Should accept at least one argument (target path)
    if len(params) < 1:
        return (False, f"Plugin '{name}' must accept at least one argument (target path)")

    # Try calling with a dummy path to check return type
    try:
        result = collector(Path("."))
        if not isinstance(result, MetricResult):
            return (False, f"Plugin '{name}' must return MetricResult, got {type(result).__name__}")
    except TypeError:
        return (False, f"Plugin '{name}' has wrong signature")
    except Exception:
        # Other errors are OK — the plugin might fail on invalid input
        pass

    return (True, "")
