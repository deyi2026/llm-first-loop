"""EVO-20261108-b5fead21 ③: spawn 派单引用被隐藏技能时的前置披露实测.

门禁开（LFL_SKILLS_REQUIRE_MANIFEST=1）时，任务文本引用 skills/<name> 或
skill_load('<name>') 而该技能 integrity != ok → spawn 回执携带
[技能披露警告]；纯披露不拦截派单，披露面失败 fail-open。
"""
from __future__ import annotations

import pytest

from llm_loop.llm.client import LLMResponse
from llm_loop.skills.loader import INTEGRITY_OK, scan_skills_dir, write_manifest
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool, _referenced_skill_names


@pytest.fixture()
def skills_dir(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    for name in ("alpha", "beta"):
        sub = root / name
        sub.mkdir()
        (sub / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: test skill {name}\n---\nbody\n",
            encoding="utf-8",
        )
    write_manifest(root)  # 登记 alpha/beta 基线 → 全部 ok
    # beta 在登记后被修改 → integrity=modified（今晚事故同构的"隐藏"态）
    (root / "beta" / "SKILL.md").write_text(
        "---\nname: beta\ndescription: test skill beta\n---\nbody CHANGED\n",
        encoding="utf-8",
    )
    return str(root)


def _runner(engine, fake):
    fake._responses = [LLMResponse(content="完成", tool_calls=[], provider="fake")]
    return SubAgentRunner(
        llm=fake, registry=engine.registry, session_store=engine.session, max_depth=3
    )


def _await(runner, receipt):
    import re

    from llm_loop.tools.builtin.subagent_result import SubAgentResultTool

    match = re.search(r"child_id=(subagent_[0-9a-f]+)", receipt.content)
    assert match, receipt.content
    return SubAgentResultTool(runner).execute(child_id=match.group(1), wait_seconds=5)


# ── 机械抽取 ──────────────────────────────────────────────────────────


def test_referenced_skill_names_extraction():
    text = "先加载 skills/merge-review-gate 再 skill_load('code-review-gate')，最后 skills/beta/"
    # 抽取按模式分组进行（skills/ 前缀先、skill_load() 后），断言用集合语义。
    assert sorted(_referenced_skill_names(text)) == sorted(
        ["merge-review-gate", "code-review-gate", "beta"]
    )
    # 裸名不猜（避免正文提及技能名被误判为派单依赖）
    assert _referenced_skill_names("用 beta 工具审查，alpha 辅助") == []
    assert _referenced_skill_names("") == []


# ── 应警输入（RULE-AI-35: 实测应拦/应警行为，不以代码走读代替） ────────────


def test_hidden_skill_reference_warned_in_spawn_receipt(
    build_test_engine, skills_dir, monkeypatch
):
    """门禁开 + 派单引用被隐藏技能 → 回执含警告（今晚事故同构场景）。"""
    engine, fake = build_test_engine([])
    runner = _runner(engine, fake)
    monkeypatch.setenv("LFL_SKILLS_REQUIRE_MANIFEST", "1")
    tool = SpawnSubAgentTool(runner, skills_dir_provider=lambda: skills_dir)

    receipt = tool.execute(task="按 skills/beta 的工作流执行审查")

    assert receipt.status.value == "success"  # 纯披露，不拦截派单
    assert "[技能披露警告]" in receipt.content
    assert "beta" in receipt.content
    assert "拒载" in receipt.content
    terminal = _await(runner, receipt)
    assert terminal.status.value == "success"  # child 本身正常完成


def test_ok_skill_reference_and_no_reference_stay_silent(
    build_test_engine, skills_dir, monkeypatch
):
    engine, fake = build_test_engine([])
    runner = _runner(engine, fake)
    monkeypatch.setenv("LFL_SKILLS_REQUIRE_MANIFEST", "1")
    tool = SpawnSubAgentTool(runner, skills_dir_provider=lambda: skills_dir)

    ok_receipt = tool.execute(task="按 skills/alpha 的工作流执行审查")
    assert "[技能披露警告]" not in ok_receipt.content
    _await(runner, ok_receipt)

    plain = tool.execute(task="直接审查，不引用任何技能")
    assert "[技能披露警告]" not in plain.content
    _await(runner, plain)


def test_gate_off_means_no_hidden_state_no_warning(
    build_test_engine, skills_dir, monkeypatch
):
    engine, fake = build_test_engine([])
    runner = _runner(engine, fake)
    monkeypatch.delenv("LFL_SKILLS_REQUIRE_MANIFEST", raising=False)
    tool = SpawnSubAgentTool(runner, skills_dir_provider=lambda: skills_dir)

    receipt = tool.execute(task="按 skills/beta 的工作流执行审查")

    assert "[技能披露警告]" not in receipt.content
    _await(runner, receipt)


# ── 兼容与 fail-open ─────────────────────────────────────────────────


def test_provider_absent_keeps_legacy_behavior(build_test_engine, skills_dir, monkeypatch):
    """旧装配（无 provider）零行为变化——不警告也不崩。"""
    engine, fake = build_test_engine([])
    runner = _runner(engine, fake)
    monkeypatch.setenv("LFL_SKILLS_REQUIRE_MANIFEST", "1")
    tool = SpawnSubAgentTool(runner)

    receipt = tool.execute(task="按 skills/beta 的工作流执行审查")

    assert receipt.status.value == "success"
    assert "[技能披露警告]" not in receipt.content
    _await(runner, receipt)


def test_disclosure_failure_is_fail_open(build_test_engine, skills_dir, monkeypatch):
    def _boom():
        raise RuntimeError("skills dir unreadable")

    engine, fake = build_test_engine([])
    runner = _runner(engine, fake)
    monkeypatch.setenv("LFL_SKILLS_REQUIRE_MANIFEST", "1")
    tool = SpawnSubAgentTool(runner, skills_dir_provider=_boom)

    receipt = tool.execute(task="按 skills/beta 的工作流执行审查")

    assert receipt.status.value == "success"  # 披露面失败不拦截派单
    assert "[技能披露警告]" not in receipt.content
    _await(runner, receipt)


def test_fixture_integrity_states_are_as_expected(skills_dir):
    metas = {m.name: m.integrity for m in scan_skills_dir(skills_dir)}
    assert metas == {"alpha": INTEGRITY_OK, "beta": "modified"}


def test_trailing_period_not_swallowed_into_skill_name():
    # 独立审查 P2-3：句尾英文句点不属于技能名（"skills/beta." → 抽出 "beta"）
    assert _referenced_skill_names("先用 skills/beta. 完成审查") == ["beta"]
    assert _referenced_skill_names("参见 skills/a.b.c 的说明") == ["a.b.c"]


def test_missing_skill_reference_disclosed(skills_dir, monkeypatch):
    # 独立审查 P2-4：引用了但本地目录无此技能 → missing 披露（child skill_load 将 not-found）
    from llm_loop.tools.builtin.spawn_subagent import _hidden_skill_warnings

    monkeypatch.setenv("LFL_SKILLS_REQUIRE_MANIFEST", "1")
    warnings = _hidden_skill_warnings(
        "请加载 skills/ghost-review-gate 后开始", lambda: str(skills_dir)
    )
    assert any("ghost-review-gate(missing)" in w for w in warnings), warnings
    # 存在且 ok 的技能仍零噪声
    assert _hidden_skill_warnings("用 skills/alpha 即可", lambda: str(skills_dir)) == []
