"""Watch mode: re-run trust-meter on file changes.

Polls for .py file changes using os.stat (no external dependencies).
Re-runs the trust meter when changes are detected.

Usage:
    python -m trust_meter.cli . --watch
    python -m trust_meter.cli . --watch --interval 5
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

SKIP_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", "node_modules", ".tox", ".trust-baselines"}


def _get_file_mtimes(root: Path) -> dict[str, float]:
    """Get modification times for all .py files."""
    mtimes: dict[str, float] = {}
    for py_file in root.rglob("*.py"):
        rel = py_file.relative_to(root).as_posix()
        if any(d in rel.split("/") for d in SKIP_DIRS):
            continue
        try:
            mtimes[rel] = os.path.getmtime(py_file)
        except OSError:
            continue
    return mtimes


def _detect_changes(old: dict[str, float], new: dict[str, float]) -> list[str]:
    """Detect changed, added, or deleted files."""
    changes: list[str] = []

    for path, mtime in new.items():
        if path not in old:
            changes.append(f"+{path}")
        elif mtime != old[path]:
            changes.append(f"~{path}")

    for path in old:
        if path not in new:
            changes.append(f"-{path}")

    return changes


def _notify_changes(changes: list[str], on_change=None) -> None:
    """Notify about detected changes."""
    if on_change:
        on_change(changes)
    else:
        print(f"\n[{time.strftime('%H:%M:%S')}] {len(changes)} file(s) changed:")
        for c in changes[:5]:
            print(f"  {c}")
        if len(changes) > 5:
            print(f"  ... and {len(changes) - 5} more")


def _run_meter(meter_func, on_run=None) -> None:
    """Run the meter and call the on_run callback."""
    try:
        report = meter_func()
        if on_run:
            on_run(report)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)


def watch_and_run(
    root: Path,
    meter_func,
    interval: float = 2.0,
    on_change=None,
    on_run=None,
) -> None:
    """Watch for file changes and re-run the meter."""
    print(f"Watching {root} for changes (interval: {interval}s)...")
    print("Press Ctrl+C to stop.\n")

    current_mtimes = _get_file_mtimes(root)
    _run_meter(meter_func, on_run)

    try:
        while True:
            time.sleep(interval)
            new_mtimes = _get_file_mtimes(root)
            changes = _detect_changes(current_mtimes, new_mtimes)
            if changes:
                _notify_changes(changes, on_change)
                _run_meter(meter_func, on_run)
                current_mtimes = new_mtimes
    except KeyboardInterrupt:
        print("\nStopped watching.")


def _default_meter_func(root: Path):
    """Default meter function for CLI integration."""
    from trust_meter.cli import build_meter
    meter = build_meter()
    return meter.measure(root, threshold=70.0)
