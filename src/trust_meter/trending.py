"""Trending: track trust scores over time.

Stores historical scores and generates trend analysis:
- Score history
- Sparkline visualization
- Trend detection (improving/declining/stable)
- Min/max/average statistics

Usage:
    from trust_meter.trending import TrendTracker
    tracker = TrendTracker(Path("."))
    tracker.add(report)
    print(tracker.sparkline())
    print(tracker.trend())
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from trust_meter.meter import TrustReport

TRENDING_FILE = ".trust-trending.json"

# Sparkline characters (8 levels)
SPARK_CHARS = "▁▂▃▄▅▆▇█"


@dataclass
class TrendEntry:
    """A single trending data point."""

    timestamp: str
    score: float
    metrics: dict[str, float] = field(default_factory=dict)


class TrendTracker:
    """Track trust scores over time."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._file = root / TRENDING_FILE
        self._entries: list[TrendEntry] = []
        self._load()

    def _load(self) -> None:
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                self._entries = [
                    TrendEntry(
                        timestamp=e["timestamp"],
                        score=e["score"],
                        metrics=e.get("metrics", {}),
                    )
                    for e in data.get("entries", [])
                ]
            except Exception:
                self._entries = []

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "entries": [
                {"timestamp": e.timestamp, "score": e.score, "metrics": e.metrics}
                for e in self._entries
            ]
        }
        self._file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def add(self, report: TrustReport) -> None:
        """Add a trust report to the trending history."""
        metrics = {m.name: m.score for m in report.metrics}
        entry = TrendEntry(
            timestamp=report.timestamp,
            score=report.overall_score,
            metrics=metrics,
        )
        self._entries.append(entry)
        self._save()

    def add_score(self, score: float, timestamp: str = "") -> None:
        """Add a raw score to the trending history."""
        if not timestamp:
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._entries.append(TrendEntry(timestamp=timestamp, score=score))
        self._save()

    @property
    def entries(self) -> list[TrendEntry]:
        return list(self._entries)

    @property
    def count(self) -> int:
        return len(self._entries)

    @property
    def latest(self) -> TrendEntry | None:
        return self._entries[-1] if self._entries else None

    def scores(self) -> list[float]:
        return [e.score for e in self._entries]

    def average(self) -> float:
        s = self.scores()
        return sum(s) / len(s) if s else 0.0

    def min_score(self) -> float:
        s = self.scores()
        return min(s) if s else 0.0

    def max_score(self) -> float:
        s = self.scores()
        return max(s) if s else 0.0

    def sparkline(self, width: int = 20) -> str:
        """Generate a sparkline visualization of the score history."""
        scores = self.scores()
        if not scores:
            return ""

        # Sample to width
        if len(scores) > width:
            step = len(scores) / width
            sampled = [scores[int(i * step)] for i in range(width)]
        else:
            sampled = scores

        if not sampled:
            return ""

        min_s = min(sampled)
        max_s = max(sampled)
        range_s = max_s - min_s if max_s > min_s else 1

        chars = []
        for s in sampled:
            idx = int((s - min_s) / range_s * (len(SPARK_CHARS) - 1))
            chars.append(SPARK_CHARS[idx])

        return "".join(chars)

    def trend(self, window: int = 5) -> str:
        """Detect trend direction over recent entries.

        Returns: "improving", "declining", "stable", or "insufficient"
        """
        scores = self.scores()
        if len(scores) < 2:
            return "insufficient"

        recent = scores[-window:] if len(scores) >= window else scores
        if len(recent) < 2:
            return "insufficient"

        avg_first = sum(recent[:len(recent) // 2]) / (len(recent) // 2)
        avg_second = sum(recent[len(recent) // 2:]) / (len(recent) - len(recent) // 2)

        delta = avg_second - avg_first
        if delta > 2:
            return "improving"
        elif delta < -2:
            return "declining"
        return "stable"

    def to_json(self, indent: int = 2) -> str:
        """Export trending data as JSON."""
        return json.dumps({
            "count": self.count,
            "average": round(self.average(), 1),
            "min": round(self.min_score(), 1),
            "max": round(self.max_score(), 1),
            "trend": self.trend(),
            "sparkline": self.sparkline(),
            "entries": [
                {"timestamp": e.timestamp, "score": round(e.score, 1)}
                for e in self._entries
            ],
        }, indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        """Export trending data as markdown."""
        lines = [
            "# Trust Trend",
            "",
            f"**Entries:** {self.count}",
            f"**Average:** {self.average():.1f}",
            f"**Range:** {self.min_score():.1f} — {self.max_score():.1f}",
            f"**Trend:** {self.trend()}",
            f"**Sparkline:** `{self.sparkline()}`",
            "",
            "| Timestamp | Score |",
            "|-----------|-------|",
        ]
        for e in self._entries:
            lines.append(f"| {e.timestamp} | {e.score:.1f} |")
        return "\n".join(lines)
