"""Contract: the merged offline dual-agent package must stay dormant by default.

Production Web/Feishu/Learning/LoopEngine/Provider modules may not import
experimental assurance modules. Any future production integration must
explicitly remove/rewrite this guard as a separately authorized change.
"""

from __future__ import annotations

import ast
from pathlib import Path


def test_no_production_source_module_imports_offline_assurance_package():
    source = Path(__file__).resolve().parents[2] / "src" / "llm_loop"
    assert (source / "assurance" / "p112_offline_vertical.py").is_file()
    violations: list[str] = []
    for path in source.rglob("*.py"):
        if "assurance" in path.relative_to(source).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith("llm_loop.assurance"):
                    violations.append(f"{path}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for imported in node.names:
                    if imported.name.startswith("llm_loop.assurance"):
                        violations.append(f"{path}:{node.lineno}")
    assert not violations, (
        "Production import paths must not activate experimental dual Agent: "
        + ", ".join(violations[:10])
    )
