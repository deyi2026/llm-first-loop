"""前缀面契约 conformance 套件（契约：docs/design/ARCHITECTURE-cache-prefix-surface-contract-v1.md）.

转录纪律：本套件逐条转录契约 §7 不变式与 §9 验收，**不做设计解释**。
引用格式统一为「§7 第 N 条 / §9 第 N 条」（文档无小节编号，勿写 §7.3/§9.2）。

分层：
  A 行为断言 —— §7/§9 的行为性表述（基线无关，本套件唯一行为基准）；
  B 静态断言 —— §9 第 1/5 条（签名/删除面/生产调用方传参），grep+AST；
  C 头注     —— §5/§6 文件/行号/符号清单为**基线相对**（设计时基线树），
                不进断言；当前树删除面以契约 §6.1 主仓对账的在场 4 项为准。

红→绿纪律：套件先于修复落地。对偏离契约的树跑出**红**，红清单即当前偏离的存档
（主仓 8e589de 与 f938428 应给出两种不同的红签名）。
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from llm_loop.core.cache_health import CacheHealthMonitor
from llm_loop.core.history import stable_digest
from llm_loop.core.prompt_build.stages.base_assembly import run_base_assembly

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "llm_loop"
STAGES = SRC / "core" / "prompt_build" / "stages"

# ───────────────────────── A 行为断言（§7 / §9）─────────────────────────


def _drift(m: CacheHealthMonitor) -> int:
    return int(m.snapshot().get("gate_drift_count", -1))


def test_A1_c7_1_gate_fail_open() -> None:
    """§7 第 1 条：门禁任何内部异常不得外溢（fail-open）。"""
    m = CacheHealthMonitor()
    m._baselines = None  # 内部状态损坏 → 内部抛 AttributeError
    m.preflight("s", "sysfp-1", "toolsfp-1")   # 不得 raise
    m.postcheck("s", "sysfp-1", "toolsfp-1")   # 不得 raise


def test_A2_c7_2_steady_state_zero_cost() -> None:
    """§7 第 2 条：system/tools 双指纹不变 → 零 drift、零干预、零提示。"""
    m = CacheHealthMonitor()
    m.postcheck("s", "sysfp-1", "toolsfp-1")
    assert m.postcheck("s", "sysfp-1", "toolsfp-1") is None
    m.preflight("s", "sysfp-1", "toolsfp-1")
    assert _drift(m) == 0, "§7 第 2 条：稳态不得计入 drift"
    assert m.force_head_keep_for("s") is False


def test_A3_c7_3_tools_axis_never_intervenes() -> None:
    """§7 第 3 条（核心）：tools 指纹独变 = 合法变更 → 仅审计，绝不干预。"""
    m = CacheHealthMonitor()
    m.postcheck("s", "sysfp-1", "toolsfp-1")
    m.preflight("s", "sysfp-1", "toolsfp-2")  # tools 独变
    assert m.force_head_keep_for("s") is False, (
        "§7 第 3 条：tools 轴独变不得触发 force_head_keep"
    )
    assert _drift(m) == 0, "§7 第 3 条：tools 轴独变不得计入 gate_drift_count"


def test_A4_c7_3_system_axis_is_drift() -> None:
    """§7 第 3 条（核心）：system 指纹独变 = 真漂移 → drift + 干预 + 可观测出口。"""
    m = CacheHealthMonitor()
    m.postcheck("s", "sysfp-1", "toolsfp-1")
    m.preflight("s", "sysfp-2", "toolsfp-1")  # system 独变
    assert _drift(m) == 1, "§7 第 3 条：system 轴独变必须计入 gate_drift_count"
    assert m.force_head_keep_for("s") is True, (
        "§7 第 3 条：system 轴独变必须触发 force_head_keep"
    )
    assert m.take_gate_note("s") is True, "§9 第 2 条：告警出口必须可观测"


def test_A5_c9_2_tools_change_counted_not_intervening() -> None:
    """§9 第 2 条：tools 独变 → 无提示 + `_tools_change_count` 计 1（不进 snapshot）。"""
    m = CacheHealthMonitor()
    m.postcheck("s", "sys", "toolsfp-1")
    hint = m.postcheck("s", "sys", "toolsfp-2")  # tools 独变
    assert hint is None, "§9 第 2 条：tools 独变不得产生拼装合规提示"
    assert getattr(m, "_tools_change_count", -1) == 1, (
        "§9 第 2 条：tools 独变必须使 _tools_change_count 自增（进程内计数器）"
    )
    assert "tools_change_count" not in m.snapshot(), (
        "§10 Q2（已决）：_tools_change_count 不进 snapshot"
    )


def test_A6_c9_2_system_change_hint_and_drift() -> None:
    """§9 第 2 条：system 独变 → postcheck 返回合规提示 + drift 计数。"""
    m = CacheHealthMonitor()
    m.postcheck("s", "sysfp-1", "toolsfp-1")
    hint = m.postcheck("s", "sysfp-2", "toolsfp-1")  # system 独变
    assert hint is not None, "§9 第 2 条：system 独变必须返回拼装合规提示"
    assert _drift(m) == 1


def test_A7_c9_3_system_fp_same_form_as_projection_gate() -> None:
    """§9 第 3 条 + §5 第 2 条：result.system_fp == stable_digest(system_prompt) 裸字符串。"""
    res = _assemble(system_prompt="SYS-CONST-CONF", tool_prefix_fp="toolsfp-1")
    assert getattr(res, "system_fp", None) == stable_digest("SYS-CONST-CONF"), (
        "§9 第 3 条：system_fp 必须为裸字符串 stable_digest(system_prompt)，"
        "与 projection_gate 同形（不得是列表形/组合形）"
    )
    assert res.system_fp != res.stable_fp, (
        "§3 R1/R2：system 轴指纹必须与组合 stable_fp 分离（双轴分离的直接证据）"
    )


def test_A8_c7_4_combined_fp_boundary_sensitivity() -> None:
    """§7 第 4 条：combined stable_fp 对 tools 变化保持敏感（边界保护输入）。"""
    a = _assemble(system_prompt="SYS-CONST-CONF", tool_prefix_fp="toolsfp-1")
    b = _assemble(system_prompt="SYS-CONST-CONF", tool_prefix_fp="toolsfp-2")
    c = _assemble(system_prompt="SYS-CONST-CONF", tool_prefix_fp="toolsfp-1")
    assert a.stable_fp == c.stable_fp, "§7 第 4 条：同 tools → combined 指纹不变"
    assert a.stable_fp != b.stable_fp, (
        "§7 第 4 条：tools 变 → combined 指纹必须变化（_cache_boundary_protection 输入）"
    )


# ───────────────────────── B 静态断言（§9 第 1/5 条）─────────────────────────


def test_B1_c9_1_gate_signatures() -> None:
    """§9 第 1 条：preflight/postcheck 签名 == (session_id, system_fp, tools_fp)。"""
    for name in ("preflight", "postcheck"):
        params = list(inspect.signature(getattr(CacheHealthMonitor, name)).parameters)
        assert params == ["self", "session_id", "system_fp", "tools_fp"], (
            f"§9 第 1 条：{name} 签名偏离契约，实际 {params}"
        )


def test_B2_c9_5_deleted_symbols_unreferenced() -> None:
    """§9 第 5 条：删除面符号在 src/ 全库零引用（清单 = 契约 §6.1 在场 4 项）。"""
    dead = re.compile(
        r"_skel_baselines|_controlled_change_count|_model_prefix_contract"
        r"|_contract_drift_count|skeleton_fp"
    )
    hits = [
        f"{p.relative_to(REPO_ROOT)}:{i + 1}: {line.strip()[:80]}"
        for p in sorted(SRC.rglob("*.py"))
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines())
        if dead.search(line)
    ]
    assert not hits, "§9 第 5 条：以下残留引用必须删除：\n" + "\n".join(hits)


def test_B3_c9_1_production_callers_pass_both_axes() -> None:
    """§9 第 1 条（尾句）：生产调用方必须同时传双轴（防「分支全绿、生产不传参」退化）。"""
    for fname in ("base_assembly.py", "tail_assembly.py"):
        tree = ast.parse((STAGES / fname).read_text(encoding="utf-8"))
        calls = [
            c for c in ast.walk(tree)
            if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute)
            and c.func.attr in ("preflight", "postcheck")
        ]
        assert calls, f"§9 第 1 条：{fname} 未找到 preflight/postcheck 生产调用"
        for c in calls:
            kw = {k.arg for k in c.keywords}
            ok = len(c.args) >= 3 or {"system_fp", "tools_fp"} <= kw
            assert ok, (
                f"§9 第 1 条：{fname} 的 {c.func.attr} 调用未传双轴"
                f"（positional={len(c.args)}, keywords={sorted(kw) or '-'}）"
            )


def test_B4_c9_5_snapshot_surface() -> None:
    """§6.1 + §10 Q2：snapshot 不再暴露 controlled_change_count；tools_change_count 不入。"""
    snap = CacheHealthMonitor().snapshot()
    assert "controlled_change_count" not in snap, (
        "§6.1：controlled_change_count（骨架分级残面）应随分级机制一并删除"
    )
    assert "tools_change_count" not in snap, "§10 Q2（已决）：不入 snapshot"


def test_B5_c7_5_projection_gate_untouched() -> None:
    """§7 第 5 条：projection_gate 的 system_fp=stable_digest(system_prompt) 裸字符串不得回退。"""
    tree = ast.parse(
        (STAGES / "projection_gate.py").read_text(encoding="utf-8")
    )
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.keywords:
            continue
        for kw in node.keywords:
            if kw.arg != "system_fp" or not isinstance(kw.value, ast.Call):
                continue
            fn, args = kw.value.func, kw.value.args
            if (
                isinstance(fn, ast.Name) and fn.id == "stable_digest"
                and len(args) == 1 and isinstance(args[0], ast.Name)
                and args[0].id == "system_prompt"
            ):
                found = True
    assert found, "§7 第 5 条：projection_gate 必须保留裸字符串 system_fp=stable_digest(system_prompt)"


# ───────────────────────── 辅助 ─────────────────────────


def _noop_inject(base, prefix_len, session_id):  # noqa: ANN001, ANN202
    return base, prefix_len


def _assemble(*, system_prompt: str, tool_prefix_fp: str):
    kwargs = dict(
        base=[],
        system_prompt=system_prompt,
        session_id="conformance-suite",
        sess_message_count=0,
        sess_anchor=None,
        inject_interop=_noop_inject,
        cache_monitor=CacheHealthMonitor(),
        tool_prefix_fp=tool_prefix_fp,
    )
    try:
        return run_base_assembly(**kwargs)
    except TypeError as exc:  # 签名偏离也是契约偏离，不得静默跳过
        pytest.fail(f"§5 第 2 条：run_base_assembly 无法按契约形态调用：{exc}")
