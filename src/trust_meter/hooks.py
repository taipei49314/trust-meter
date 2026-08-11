"""Git hooks: install pre-commit trust checks.

Installs a pre-commit hook that runs trust-meter before each commit.
If the trust score drops below threshold, the commit is blocked.

Usage:
    python -m trust_meter.hooks install
    python -m trust_meter.hooks uninstall
"""

from __future__ import annotations

import sys
from pathlib import Path

HOOK_NAME = "pre-commit"
HOOK_SCRIPT = """#!/bin/sh
# trust-meter pre-commit hook
# Auto-generated — do not edit manually

echo "Running trust-meter pre-commit check..."
python -m trust_meter.cli . --strict --phase "pre-commit"
RESULT=$?

if [ $RESULT -ne 0 ]; then
    echo ""
    echo "TRUST CHECK FAILED — commit blocked."
    echo "Fix the issues above, then try again."
    echo "To skip this check: git commit --no-verify"
    exit 1
fi

echo "Trust check passed."
"""


def install_hook(repo_root: Path) -> Path:
    """Install the pre-commit hook."""
    hooks_dir = repo_root / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    hook_path = hooks_dir / HOOK_NAME
    hook_path.write_text(HOOK_SCRIPT, encoding="utf-8")

    # Make executable on Unix
    try:
        hook_path.chmod(0o755)
    except (OSError, AttributeError):
        pass  # Windows doesn't use chmod

    return hook_path


def uninstall_hook(repo_root: Path) -> bool:
    """Remove the pre-commit hook if it was installed by trust-meter."""
    hook_path = repo_root / ".git" / "hooks" / HOOK_NAME
    if not hook_path.exists():
        return False

    content = hook_path.read_text(encoding="utf-8")
    if "trust-meter pre-commit hook" not in content:
        return False  # Not our hook

    hook_path.unlink()
    return True


def is_installed(repo_root: Path) -> bool:
    """Check if the trust-meter pre-commit hook is installed."""
    hook_path = repo_root / ".git" / "hooks" / HOOK_NAME
    if not hook_path.exists():
        return False
    content = hook_path.read_text(encoding="utf-8")
    return "trust-meter pre-commit hook" in content


def main() -> int:
    """CLI for hook management."""
    if len(sys.argv) < 2:
        print("Usage: python -m trust_meter.hooks [install|uninstall|status]")
        return 1

    command = sys.argv[1]
    repo_root = Path(".")

    if command == "install":
        path = install_hook(repo_root)
        print(f"Pre-commit hook installed: {path}")
        return 0
    elif command == "uninstall":
        if uninstall_hook(repo_root):
            print("Pre-commit hook removed.")
        else:
            print("No trust-meter hook found.")
        return 0
    elif command == "status":
        if is_installed(repo_root):
            print("Pre-commit hook: INSTALLED")
        else:
            print("Pre-commit hook: NOT INSTALLED")
        return 0
    else:
        print(f"Unknown command: {command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
