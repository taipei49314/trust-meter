"""Tests for the architecture metric."""

import tempfile
from pathlib import Path

from trust_meter.metrics.architecture import (
    collect_architecture, _build_local_import_graph,
    _find_cycles, _max_coupling, _max_chain_depth,
)


def _make_project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_no_modules():
    d = _make_project({})
    result = collect_architecture(d)
    assert result.score == 100.0
    assert result.passed is True


def test_clean_graph():
    d = _make_project({
        "src/main.py": "import utils\nx = 1\n",
        "src/utils.py": "y = 2\n",
    })
    result = collect_architecture(d)
    assert result.passed is True
    assert "0 cycle(s)" in result.details


def test_circular_dependency():
    d = _make_project({
        "src/a.py": "import b\nx = 1\n",
        "src/b.py": "import a\ny = 2\n",
    })
    result = collect_architecture(d)
    assert result.passed is False
    assert any("cycle" in e for e in result.evidence)
    assert result.score < 100.0


def test_three_way_cycle():
    d = _make_project({
        "src/a.py": "import b\n",
        "src/b.py": "import c\n",
        "src/c.py": "import a\n",
    })
    result = collect_architecture(d)
    assert result.passed is False
    assert any("cycle" in e for e in result.evidence)


def test_no_cycle_self_import():
    """A module importing itself should not create a cycle."""
    d = _make_project({
        "src/a.py": "import a\nx = 1\n",
    })
    graph = _build_local_import_graph(d)
    # Self-import should be filtered out
    assert "a" not in graph.get("a", set())


def test_high_coupling():
    modules = {f"src/m{i}.py": f"x = {i}\n" for i in range(20)}
    modules["src/main.py"] = "\n".join(f"import m{i}" for i in range(20)) + "\n"
    d = _make_project(modules)
    result = collect_architecture(d)
    assert any("coupling" in e for e in result.evidence)


def test_find_cycles_empty():
    assert _find_cycles({}) == []


def test_find_cycles_none():
    graph = {"a": {"b"}, "b": {"c"}, "c": set()}
    assert _find_cycles(graph) == []


def test_find_cycles_simple():
    graph = {"a": {"b"}, "b": {"a"}}
    cycles = _find_cycles(graph)
    assert len(cycles) >= 1
    # Cycle should contain both a and b
    cycle = cycles[0]
    assert "a" in cycle
    assert "b" in cycle


def test_max_coupling_empty():
    assert _max_coupling({}) == ("", 0)


def test_max_coupling():
    graph = {"a": {"b", "c"}, "b": {"c"}}
    mod, count = _max_coupling(graph)
    assert mod == "a"
    assert count == 2


def test_max_chain_depth_empty():
    assert _max_chain_depth({}) == 0


def test_max_chain_depth_linear():
    graph = {"a": {"b"}, "b": {"c"}, "c": set()}
    assert _max_chain_depth(graph) == 2


def test_max_chain_depth_diamond():
    graph = {"a": {"b", "c"}, "b": {"d"}, "c": {"d"}, "d": set()}
    assert _max_chain_depth(graph) == 2


def test_graph_results_do_not_depend_on_dict_or_set_iteration_order():
    class IterationOrderedSet(set):
        def __init__(self, values):
            ordered_values = tuple(values)
            super().__init__(ordered_values)
            self._ordered_values = ordered_values

        def __iter__(self):
            return iter(self._ordered_values)

    forward = {
        "a": IterationOrderedSet(["b", "c"]),
        "b": IterationOrderedSet(["a"]),
        "c": IterationOrderedSet(["a"]),
        "d": IterationOrderedSet(["b", "c"]),
    }
    reverse = {
        "d": IterationOrderedSet(["c", "b"]),
        "c": IterationOrderedSet(["a"]),
        "b": IterationOrderedSet(["a"]),
        "a": IterationOrderedSet(["c", "b"]),
    }

    assert _find_cycles(forward) == _find_cycles(reverse) == [
        ["a", "b", "a"],
        ["a", "c", "a"],
    ]
    assert _max_coupling(forward) == _max_coupling(reverse) == ("a", 2)
    assert _max_chain_depth(forward) == _max_chain_depth(reverse)


def test_build_local_graph():
    d = _make_project({
        "src/a.py": "import b\nimport os\n",
        "src/b.py": "import sys\n",
    })
    graph = _build_local_import_graph(d)
    assert "b" in graph.get("a", set())
    # os and sys are stdlib, should not be in graph
    assert "os" not in graph.get("a", set())
    assert "sys" not in graph.get("b", set())


def test_from_import():
    d = _make_project({
        "src/a.py": "from b import func\n",
        "src/b.py": "def func(): pass\n",
    })
    graph = _build_local_import_graph(d)
    assert "b" in graph.get("a", set())


def test_nested_import():
    """import a.b should resolve to 'a'."""
    d = _make_project({
        "src/main.py": "import utils.helpers\n",
        "src/utils.py": "x = 1\n",
    })
    graph = _build_local_import_graph(d)
    assert "utils" in graph.get("main", set())


def test_architecture_details():
    d = _make_project({
        "src/a.py": "import b\n",
        "src/b.py": "x = 1\n",
    })
    result = collect_architecture(d)
    assert "modules" in result.details
    assert "edges" in result.details
    assert "cycle" in result.details
