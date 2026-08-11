"""Config file support: .trust-meter.toml

Zero dependencies — uses a simple TOML-like parser.

Example .trust-meter.toml:
```
[trust-meter]
threshold = 80.0
phase_gate = "Phase 1"

[skip]
patterns = ["vendor/*", "generated/*"]

[weights]
determinism = 1.0
locality = 1.0
evidence = 1.0
reproducibility = 1.0
architecture = 1.0
transparency = 0.5

[limits]
max_function_lines = 50
max_file_lines = 500
max_imports_per_module = 15
max_chain_depth = 10
```
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


CONFIG_FILENAME = ".trust-meter.toml"


@dataclass
class Config:
    """Trust-meter configuration."""

    threshold: float = 70.0
    phase_gate: str = ""
    strict: bool = False
    skip_patterns: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    limits: dict[str, int] = field(default_factory=dict)

    def get_weight(self, name: str, default: float = 1.0) -> float:
        return self.weights.get(name, default)

    def get_limit(self, name: str, default: int = 0) -> int:
        return self.limits.get(name, default)


def find_config(start: Path) -> Path | None:
    """Walk up from start to find .trust-meter.toml."""
    current = start.resolve()
    while True:
        candidate = current / CONFIG_FILENAME
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def parse_config(text: str) -> Config:
    """Parse a .trust-meter.toml file. Zero external dependencies."""
    config = Config()

    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Section header
        section_match = re.match(r"^\[([^\]]+)\]$", stripped)
        if section_match:
            section = section_match.group(1).strip()
            continue

        # Key-value pair
        kv_match = re.match(r'^(\w+)\s*=\s*(.+)$', stripped)
        if not kv_match:
            continue

        key = kv_match.group(1).strip()
        value = kv_match.group(2).strip()

        if section == "trust-meter":
            if key == "threshold":
                config.threshold = _parse_float(value, 70.0)
            elif key == "phase_gate":
                config.phase_gate = _parse_string(value, "")
            elif key == "strict":
                config.strict = _parse_bool(value, False)

        elif section == "skip":
            if key == "patterns":
                config.skip_patterns = _parse_list(value)

        elif section == "weights":
            config.weights[key] = _parse_float(value, 1.0)

        elif section == "limits":
            config.limits[key] = _parse_int(value, 0)

    return config


def load_config(target: Path) -> Config:
    """Load config from the target directory or its parents."""
    config_path = find_config(target)
    if config_path:
        return parse_config(config_path.read_text(encoding="utf-8"))
    return Config()


def _parse_string(value: str, default: str) -> str:
    match = re.match(r'^"([^"]*)"$', value)
    return match.group(1) if match else default


def _parse_float(value: str, default: float) -> float:
    try:
        return float(value)
    except ValueError:
        return default


def _parse_int(value: str, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _parse_bool(value: str, default: bool) -> bool:
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False
    return default


def _parse_list(value: str) -> list[str]:
    match = re.match(r'^\[([^\]]*)\]$', value)
    if not match:
        return []
    items = match.group(1)
    return [item.strip().strip('"').strip("'") for item in items.split(",") if item.strip()]
