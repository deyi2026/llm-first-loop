"""AI rule/document separation contract after R8.24-A / agency-first.

The detailed SoT and lite playbook remain versioned maintenance artifacts. They are
not a mandatory per-user-turn instruction channel. Mechanical tests protect both
directions: rules remain discoverable/versioned, and operational playbook text cannot
creep back into the universal system prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (_ROOT / path).read_text(encoding="utf-8")


def test_universal_prompt_does_not_mirror_rule_playbook():
    prompt = _read("src/llm_loop/core/prompt.py")
    for forbidden in (
        "ai_rules.lite.md",
        "read_file(full=true)",
        "rules_version",
        "reasoning_content",
        "tool_call_id",
        "search_archive",
        "search_records",
        "[[memory]]",
        "SYSTEM_PROMPT_EXTRA",
        "LFL_SYSTEM_EXTRA_BUNDLE",
    ):
        # Environment names may appear only in explanatory comments/docstrings if we
        # put them there later; current implementation intentionally has none.
        assert forbidden not in prompt, f"universal prompt regained playbook authority: {forbidden}"


def test_universal_prompt_keeps_only_small_static_responsibility_root():
    import sys

    sys.path.insert(0, str(_ROOT / "src"))
    from llm_loop.core.prompt import build_system_prompt

    prompt = build_system_prompt()
    assert "llm-first-loop" in prompt
    assert "程序提供工具和运行环境" in prompt
    assert "不替你制定任务策略或完成裁决" in prompt
    assert "当前用户指令是任务授权真值" in prompt
    assert "简短回复只绑定最近相关交互" in prompt
    assert len(prompt) < 400
    assert build_system_prompt("ignored-policy") == prompt


def test_lite_files_are_versioned_and_small_maintenance_artifacts():
    versions: set[str] = set()
    for name in ("docs/ai_rules.lite.md", "docs/ai_rules.lite.en.md"):
        p = _ROOT / name
        assert p.exists(), f"{name} 缺失"
        content = p.read_text(encoding="utf-8")
        header = content.splitlines()[0]
        match = re.search(r"version=(\d+)", header)
        assert match, f"{name} 首行缺 version=N 标记"
        versions.add(match.group(1))
    assert len(versions) == 1, f"中英文 lite 版本漂移: {versions}"
    assert len(_read("docs/ai_rules.lite.md")) < 3000


def test_lite_declares_non_global_role_and_agency_first():
    lite = _read("docs/ai_rules.lite.md")
    sot = _read("docs/ai_rules.md")
    assert "普通用户 run" in lite
    assert "零引用" in lite
    assert "agency-first" in lite.lower()
    assert "不是普通 user run 的 universal prompt" in sot
    assert "SYSTEM_PROMPT_EXTRA" in sot  # documented as retired/no-authority
    assert "无 universal prompt 写权限" in sot
    assert "RULE-AI-23" in sot
    assert "RULE-AI-24" in sot
    assert "docs/DEVELOPMENT_REPAIR_SAFETY.md" in sot
    assert "历史提议不得自我授权" in sot
    assert "短回复最近绑定" in sot


def test_lite_version_matches_snapshot_reader():
    import sys

    sys.path.insert(0, str(_ROOT / "src"))
    from llm_loop.introspection.status import _rules_version

    header = _read("docs/ai_rules.lite.md").splitlines()[0]
    match = re.search(r"version=(\d+)", header)
    assert match
    assert _rules_version() == match.group(1)
