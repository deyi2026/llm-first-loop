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
    # 1117 chars since SOUL.MD 前置逐字钉入(用户指令 2026-10-09); 仍属小型静态职责根
    assert len(prompt) < 1200
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
    assert "RULE-AI-25" in sot
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


def test_rule2931_record_and_scoring_notes_declare_three_layer_semantics():
    """TASK-fdc7603b-001 A 线: Rule29/31 记录与计分说明区分三层口径（SoT 锚定）.

    设计草案 v3 P1 规则对齐: 声明净分（usage_net 机械计分）/ 模型收益自评
    （record_use benefit）/ 独立验证（qualification task_benefit）三层分开。
    只锚定"记录与计分说明"文本；计分定义（+1/-1 语义与留痕口径）必须保持不动，
    故同时锚定计分原文仍在。2026-10-18 起"必须记录/必须评分"的义务已撤销、
    改为可选；下述断言仍锚定留痕发生时的唯一计分口径，而非使用前的强制义务。
    """
    sot = _read("docs/ai_rules.md")
    rule29 = sot.split("## 规则二十九：", 1)[1].split("\n## 规则三十：", 1)[0]
    rule31 = sot.split("## 规则三十一：", 1)[1].split("\n## 规则三十二：", 1)[0]
    # 三层口径说明（记录与计分说明层）
    assert "声明净分" in rule31
    assert "未独立验证的 applied/adapted 亦计 +1" in rule31
    assert "benefit" in rule31 and "模型自评" in rule31
    assert "task_benefit" in rule31 and "独立验证" in rule31
    assert "不被评分改变" in rule31  # 规则权威与卡片资格不被评分改变
    assert "模型收益自评" in rule29  # Rule29 记录说明同步 benefit 自评口径
    # 规范性义务语义零改动锚点（原文保持，说明性追加不得触碰）
    assert "最迟在当前任务收口（最终答复 / goal complete）前完成" in rule29
    assert "且任务结果验证有效 = **+1**" in rule31  # 第 2 条计分义务原文未动
