"""Self-audit script: run trust-meter against itself.

Usage: python scripts/self_audit.py
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from trust_meter.cli import build_meter
from trust_meter.report import generate_report


def main() -> int:
    """Run trust-meter against itself and print results."""
    root = Path(__file__).parent.parent
    meter = build_meter()
    report = generate_report(root, meter, phase_gate="Self-audit", threshold=90.0)

    print(report.summary_line())
    print()

    for m in report.metrics:
        status = "PASS" if m.passed else "FAIL"
        print(f"  [{status}] {m.name}: {m.score:.0f}/100 — {m.details}")

    print()
    if report.passed:
        print("Self-audit PASSED")
        return 0
    else:
        print("Self-audit FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
