"""The submitted bot never references opponent, test or tool sources."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_never_imports_or_reads_development_or_opponent_sources():
    forbidden = {"league", "tools", "tests"}
    for path in [ROOT / "agent.py", *(ROOT / "bot").glob("*.py")]:
        tree = ast.parse(path.read_text())
        # Existing launcher instructions in module docstrings are documentation,
        # not runtime imports or file access. Do not edit protected plumbing.
        docstrings = {id(node.value) for node in ast.walk(tree)
                      if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                      and isinstance(node.value.value, str)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(n.name.split(".")[0] in forbidden for n in node.names), path
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden, path
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                value = node.value.replace("\\", "/")
                assert not any(f"{name}/" in value or value == name for name in forbidden), (path, value)
            if isinstance(node, ast.Call):
                name = node.func
                assert not (isinstance(name, ast.Attribute) and name.attr == "sleep"), path
                assert not (isinstance(name, ast.Name) and name.id == "sleep"), path

