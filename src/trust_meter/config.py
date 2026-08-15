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

import hashlib
import math
import os
import re
import stat
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


CONFIG_FILENAME = ".trust-meter.toml"
MAX_CONFIG_BYTES = 64 * 1024
MAX_CONFIG_LINE_CHARS = 4096
MAX_PHASE_GATE_CHARS = 128


class ConfigError(ValueError):
    """An exact configuration input could not be admitted."""


def has_disallowed_text_character(text: str, *, allowed_whitespace: str) -> bool:
    """Reject whitespace and Unicode category C outside explicit allowances."""
    for character in text:
        if character.isspace() and character not in allowed_whitespace:
            return True
        if (
            unicodedata.category(character).startswith("C")
            and character not in allowed_whitespace
        ):
            return True
    return False


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


@dataclass(frozen=True)
class ExactConfig:
    """A strict config parsed from the same bytes named by its digest."""

    config: Config
    sha256: str
    byte_length: int


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


def _apply_trust_meter(config: Config, key: str, value: str) -> None:
    """Apply a trust-meter section key-value pair."""
    if key == "threshold":
        config.threshold = _parse_float(value, 70.0)
    elif key == "phase_gate":
        config.phase_gate = _parse_string(value, "")
    elif key == "strict":
        config.strict = _parse_bool(value, False)


def _apply_skip(config: Config, key: str, value: str) -> None:
    """Apply a skip section key-value pair."""
    if key == "patterns":
        config.skip_patterns = _parse_list(value)


_SECTION_HANDLERS = {
    "trust-meter": _apply_trust_meter,
    "skip": _apply_skip,
}


def parse_config(text: str) -> Config:
    """Parse a .trust-meter.toml file. Zero external dependencies."""
    config = Config()
    section = ""

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        section_match = re.match(r"^\[([^\]]+)\]$", stripped)
        if section_match:
            section = section_match.group(1).strip()
            continue

        kv_match = re.match(r'^(\w+)\s*=\s*(.+)$', stripped)
        if not kv_match:
            continue

        key = kv_match.group(1).strip()
        value = kv_match.group(2).strip()

        if section in _SECTION_HANDLERS:
            _SECTION_HANDLERS[section](config, key, value)
        elif section == "weights":
            config.weights[key] = _parse_float(value, 1.0)
        elif section == "limits":
            config.limits[key] = _parse_int(value, 0)

    return config


def parse_config_strict(text: str) -> Config:
    """Parse the core-effective config subset and reject every ambiguity.

    This parser is intentionally narrower than TOML. It exists for callers
    that need a bounded, fail-closed input contract. Only the three values
    actually applied by the core CLI are admitted; the legacy parser remains
    backward compatible for automatic discovery.
    """
    if has_disallowed_text_character(text, allowed_whitespace=" \t\r\n"):
        raise ConfigError(
            "config contains non-ASCII whitespace or a Unicode category C character"
        )
    if len(text.encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ConfigError(f"config exceeds {MAX_CONFIG_BYTES} bytes")

    config = Config()
    section = ""
    seen_sections: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()

    for line_number, line in enumerate(text.splitlines(), 1):
        if len(line) > MAX_CONFIG_LINE_CHARS:
            raise ConfigError(f"line {line_number} exceeds {MAX_CONFIG_LINE_CHARS} characters")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        section_match = re.fullmatch(r"\[([A-Za-z][A-Za-z0-9-]*)\]", stripped)
        if section_match:
            section = section_match.group(1)
            if section != "trust-meter":
                raise ConfigError(f"line {line_number}: unknown section [{section}]")
            if section in seen_sections:
                raise ConfigError(f"line {line_number}: duplicate section [{section}]")
            seen_sections.add(section)
            continue

        if not section:
            raise ConfigError(f"line {line_number}: key appears before a section")
        kv_match = re.fullmatch(
            r"([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(.+)", stripped
        )
        if not kv_match:
            raise ConfigError(f"line {line_number}: malformed assignment")
        key = kv_match.group(1)
        value = kv_match.group(2).strip()
        identity = (section, key)
        if identity in seen_keys:
            raise ConfigError(f"line {line_number}: duplicate key [{section}].{key}")
        seen_keys.add(identity)

        if key == "threshold":
            config.threshold = _strict_float(
                value, line_number, minimum=0.0, maximum=100.0
            )
        elif key == "phase_gate":
            config.phase_gate = _strict_string(
                value, line_number, maximum=MAX_PHASE_GATE_CHARS
            )
        elif key == "strict":
            config.strict = _strict_bool(value, line_number)
        else:
            raise ConfigError(f"line {line_number}: unknown key [trust-meter].{key}")

    return config


def load_config_exact(path: Path) -> ExactConfig:
    """Read one regular file once, hash those bytes, and parse them strictly.

    There is deliberately no target-relative or ancestor fallback here.
    """
    raw_path = Path(path)
    try:
        path_stat = raw_path.lstat()
    except FileNotFoundError as error:
        raise ConfigError(f"config file does not exist: {raw_path}") from error
    except OSError as error:
        raise ConfigError(f"cannot inspect config file {raw_path}: {error}") from error

    if _is_link_or_reparse(path_stat):
        raise ConfigError("config file must not be a symlink or reparse point")
    if not stat.S_ISREG(path_stat.st_mode):
        raise ConfigError("config path must name a regular file")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(raw_path, flags)
    except OSError as error:
        raise ConfigError(f"cannot open config file {raw_path}: {error}") from error

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ConfigError("config path must remain a regular file")
        if _stat_identity(path_stat) != _stat_identity(before):
            raise ConfigError("config file changed before it was opened")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read(MAX_CONFIG_BYTES + 1)
        after = os.fstat(descriptor)
    except ConfigError:
        raise
    except OSError as error:
        raise ConfigError(f"cannot read config file {raw_path}: {error}") from error
    finally:
        os.close(descriptor)

    if len(data) > MAX_CONFIG_BYTES:
        raise ConfigError(f"config exceeds {MAX_CONFIG_BYTES} bytes")
    if _stat_identity(before) != _stat_identity(after) or before.st_size != len(data):
        raise ConfigError("config file changed while it was being read")

    try:
        post_stat = raw_path.lstat()
    except OSError as error:
        raise ConfigError("config path changed after it was read") from error
    if (
        _is_link_or_reparse(post_stat)
        or not stat.S_ISREG(post_stat.st_mode)
        or _stat_identity(post_stat) != _stat_identity(after)
    ):
        raise ConfigError("config path changed after it was read")

    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ConfigError("config file is not strict UTF-8") from error

    return ExactConfig(
        config=parse_config_strict(text),
        sha256=hashlib.sha256(data).hexdigest(),
        byte_length=len(data),
    )


def _is_link_or_reparse(info) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & reparse_flag
    )


def _stat_identity(info) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        stat.S_IFMT(info.st_mode),
        info.st_size,
        getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000)),
    )


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


def _strict_string(value: str, line_number: int, maximum: int) -> str:
    match = re.fullmatch(r'"([^"\\\r\n]*)"', value)
    if not match:
        raise ConfigError(f"line {line_number}: expected a simple double-quoted string")
    parsed = match.group(1)
    if len(parsed) > maximum:
        raise ConfigError(f"line {line_number}: string exceeds {maximum} characters")
    if has_disallowed_text_character(parsed, allowed_whitespace=" "):
        raise ConfigError(
            f"line {line_number}: non-ASCII whitespace and Unicode category C "
            "characters are not allowed"
        )
    return parsed


def _strict_float(value: str, line_number: int, minimum: float, maximum: float) -> float:
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value):
        raise ConfigError(f"line {line_number}: expected a decimal number")
    parsed = float(value)
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise ConfigError(
            f"line {line_number}: number must be finite and between {minimum:g} and {maximum:g}"
        )
    return 0.0 if parsed == 0 else parsed


def _strict_bool(value: str, line_number: int) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ConfigError(f"line {line_number}: boolean must be true or false")
