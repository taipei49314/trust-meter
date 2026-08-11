[project]
name = "trust-meter"
min_python = "3.9"

[assertions]
modules = ["meter", "spec", "evidence", "report", "cli", "determinism", "locality", "evidence", "reproducibility", "transparency"]
require_tests = true
require_docstrings = true
max_function_lines = 50
