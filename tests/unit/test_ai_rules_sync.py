"""Rule/document separation contract after prompt-authority retirement."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

def _read(path: str) -> str:
    return (_ROOT / path).read_text(encoding="utf-8")

def test_universal_prompt_does_not_mirror_rule_playbook():
    source = _read("src/llm_loop/core/prompt.py")
    for forbidden in ("ai_rules.lite.md", "read_file(full=true)", "rules_version", "reasoning_content", "tool_call_id", "search_archive", "search_records", "[[memory]]"):
        assert forbidden not in source

def test_universal_prompt_keeps_small_static_responsibility_root():
    import sys
    sys.path.insert(0, str(_ROOT / "src"))
    from llm_loop.core.prompt import build_system_prompt
    prompt = build_system_prompt()
    assert "llm-first-loop" in prompt
    assert "程序提供工具和运行环境" in prompt
    assert "不替你制定任务策略或完成裁决" in prompt
    assert len(prompt) == 64
    assert build_system_prompt("ignored-policy") == prompt

def test_lite_files_are_versioned_small_maintenance_artifacts():
    versions: set[str] = set()
    for name in ("docs/ai_rules.lite.md", "docs/ai_rules.lite.en.md"):
        content = _read(name)
        match = re.search(r"version=(\d+)", content.splitlines()[0])
        assert match
        versions.add(match.group(1))
    assert versions == {"8"}
    assert len(_read("docs/ai_rules.lite.md")) < 3000
    assert "普通用户 run 零引用" in _read("docs/ai_rules.lite.md")

def test_sot_declares_no_hidden_universal_prompt_authority():
    sot = _read("docs/ai_rules.md")
    assert "不是普通 user run 的 universal prompt" in sot
    assert "无 universal prompt 写权限" in sot
    assert "DELETE GLOBAL PROMPT AUTHORITY" in sot

def test_lite_version_matches_snapshot_reader():
    import sys
    sys.path.insert(0, str(_ROOT / "src"))
    from llm_loop.introspection.status import _rules_version
    header = _read("docs/ai_rules.lite.md").splitlines()[0]
    match = re.search(r"version=(\d+)", header)
    assert match and _rules_version() == match.group(1)
