"""run_eval 代码源显式化（2026-10-27，R1-R6）纯函数测试.

零 LLM 零网络：直测 run_eval 的 code-source 纯函数与 CLI 编排——
- T1 环境陷阱：LFL_WORKSPACE_ROOT 指向 tmp 假 release（内含 src/llm_loop/__init__.py
  旧桩）+ 假 release src 占据 sys.path[0]（模拟 sitecustomize 注入）→ worktree
  路径准备仍解析 REPO/src，断言逻辑拒绝假 release 解析结果（防 sitecustomize 再抢）。
- T2 auto 漂移：解析路径≠REPO/src 且 dirty → 两路径并列告警；不 dirty / 在工作树
  解析 → 无告警。
- T3 release 断言：.releases/<hash>/src 提取 hash 并通过；在别处 → 拒。
- T4 meta 组装：三模式字段齐（与 knowledge_store 同级的形状）。
- 集成：CLI 拒未知模式；真实 main()（auto+dry，mock evaluate 输入/输出）stderr 打
  证据行且 code_source 块入 report.json / 渲染进 report.md。

载入方式与 tests/scripts/test_run_eval_knowledge_store.py 一致（sys.path 注入 scripts/）。
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import run_eval  # noqa: E402  — scripts 层模块（sys.path 注入后导入）

_FAKE_HASH = "26530f9f224bce"


def _fake_release(tmp_path: Path) -> Path:
    """tmp 假 release 工作区：.releases/<hash>/src/llm_loop/__init__.py 旧桩."""
    fake = tmp_path / "fake-ws" / ".releases" / _FAKE_HASH
    pkg = fake / "src" / "llm_loop"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        '"""旧桩：release 快照假 llm_loop."""\n', encoding="utf-8"
    )
    return fake


# ── T1 环境陷阱：worktree 准备/断言不受 LFL_WORKSPACE_ROOT 与注入路径影响 ──


def test_t1_worktree_preparation_ignores_env_trap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _fake_release(tmp_path)
    # 环境陷阱全开：workspace root 指向假 release，假 release src 已占 sys.path[0]
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(fake))
    monkeypatch.setenv("LFL_DEFAULT_WORKSPACE_ROOT", str(fake))
    monkeypatch.setenv("PYTHONPATH", str(fake / "src"))
    trapped_sys_path = [str(fake / "src"), "/usr/lib/python3.zip", "/usr/lib/python3.11"]

    src, already = run_eval.worktree_path_preparation(_REPO, trapped_sys_path)

    assert src == str(_REPO.resolve() / "src"), "插入路径必须由 REPO 决定，与环境无关"
    assert already is False, "sys.path[0] 被假 release 占据时不应判已就位"
    assert src != str(fake / "src")
    # 已就位分支：sys.path[0] 即工作树 src → 不重复插
    src2, already2 = run_eval.worktree_path_preparation(_REPO, [str(_REPO / "src"), "/other"])
    assert already2 is True and src2 == src


def test_t1_worktree_check_rejects_fake_release_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """即便插了 REPO/src 后 llm_loop 仍解析到假 release 桩（sitecustomize 再抢）→ 断言拒绝."""
    fake = _fake_release(tmp_path)
    monkeypatch.setenv("LFL_WORKSPACE_ROOT", str(fake))  # 陷阱存在也不影响断言语义
    err = run_eval.worktree_check_error(fake / "src" / "llm_loop" / "__init__.py", _REPO)
    assert err is not None, "解析到假 release 必须产生错误文本"
    assert "worktree 断言失败" in err
    assert str(_REPO / "src") in err and str(fake / "src") in err  # 期望/实际两路径并列
    # 工作树自身解析 → 通过
    assert (
        run_eval.worktree_check_error(_REPO / "src" / "llm_loop" / "__init__.py", _REPO) is None
    )


# ── T2 auto 漂移告警 ──────────────────────────────────────────────────────


def test_t2_drift_warning_only_when_drifted_and_dirty(tmp_path: Path) -> None:
    fake = _fake_release(tmp_path)
    elsewhere = fake / "src" / "llm_loop" / "__init__.py"

    warn = run_eval.drift_warning_text(elsewhere, _REPO, dirty=True)
    assert warn is not None, "漂移 + dirty 必须告警"
    assert str(fake / "src") in warn and str(_REPO / "src") in warn, "两路径并列"
    assert "--code-source" in warn, "必须提示用 --code-source 显式声明"
    assert "WARNING" in warn

    assert run_eval.drift_warning_text(elsewhere, _REPO, dirty=False) is None, "不 dirty 不告警"
    assert (
        run_eval.drift_warning_text(_REPO / "src" / "llm_loop" / "__init__.py", _REPO, dirty=True)
        is None
    ), "在工作树解析永不告警（即使 dirty）"


def test_t2b_snapshot_warning_regardless_of_dirty(tmp_path: Path) -> None:
    """R4 补口：解析落 .releases 快照必须无条件告警（干净树同样——历史"测错代码"静默面）."""
    fake = _fake_release(tmp_path)
    rel_ll = fake / "src" / "llm_loop" / "__init__.py"

    warn = run_eval.snapshot_warning_text(rel_ll)
    assert warn is not None, "落 .releases 快照必须告警，不看树脏与否"
    assert str(fake / "src") in warn and "非工作树代码" in warn, "含解析路径与非工作树提示"
    assert "--code-source" in warn, "必须提示用 --code-source 显式声明"
    assert "\n" not in warn, "单行告警"

    assert (
        run_eval.snapshot_warning_text(_REPO / "src" / "llm_loop" / "__init__.py") is None
    ), "工作树解析不告警"
    elsewhere = tmp_path / "elsewhere" / "llm_loop" / "__init__.py"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.touch()
    assert run_eval.snapshot_warning_text(elsewhere) is None, \
        "非快照外部解析不属本告警面（由漂移告警按 dirty 管辖）"


def test_t2c_resolve_auto_prints_snapshot_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R4 补口（编排面）：resolve_code_source(auto) 落快照必把快照告警打到 stderr."""
    fake = _fake_release(tmp_path)
    mod = types.ModuleType("llm_loop")
    mod.__file__ = str(fake / "src" / "llm_loop" / "__init__.py")
    monkeypatch.setitem(sys.modules, "llm_loop", mod)

    meta = run_eval.resolve_code_source("auto")

    err = capsys.readouterr().err
    assert "非工作树代码" in err and str(fake / "src") in err, "快照告警必须实际打到 stderr"
    assert "[code-source] mode=auto" in err, "证据行保持"
    assert meta["mode"] == "auto" and meta["release_hash"] is None, "auto 不记 hash（现状保持）"


# ── T3 release 断言 ───────────────────────────────────────────────────────


def test_t3_release_hash_extraction_and_rejection(tmp_path: Path) -> None:
    fake = _fake_release(tmp_path)
    rel_ll = fake / "src" / "llm_loop" / "__init__.py"

    assert run_eval.release_hash_of(rel_ll) == _FAKE_HASH
    assert run_eval.release_check_error(rel_ll) is None

    elsewhere = tmp_path / "elsewhere" / "src" / "llm_loop" / "__init__.py"
    assert run_eval.release_hash_of(elsewhere) is None
    err = run_eval.release_check_error(elsewhere)
    assert err is not None and "release 断言失败" in err
    # 工作树也不是 release：release 口径必须钉在快照上 → 拒
    assert run_eval.release_check_error(_REPO / "src" / "llm_loop" / "__init__.py") is not None


# ── T4 meta 组装：三模式字段齐 ────────────────────────────────────────────


def test_t4_meta_all_modes(tmp_path: Path) -> None:
    fake = _fake_release(tmp_path)
    rel_ll = fake / "src" / "llm_loop" / "__init__.py"
    wt_ll = _REPO / "src" / "llm_loop" / "__init__.py"
    keys = {"mode", "llm_loop_path", "release_hash", "repo_head", "dirty_llm_loop"}

    m_auto = run_eval.build_code_source_meta("auto", rel_ll, "5fa5df070", True)
    m_wt = run_eval.build_code_source_meta("worktree", wt_ll, "5fa5df070", False)
    m_rel = run_eval.build_code_source_meta("release", rel_ll, "5fa5df070", False, _FAKE_HASH)

    for m in (m_auto, m_wt, m_rel):
        assert set(m) == keys
        assert isinstance(m["dirty_llm_loop"], bool)
        assert isinstance(m["release_hash"], (str, type(None)))
    assert m_auto["release_hash"] is None and m_wt["release_hash"] is None
    assert m_rel["release_hash"] == _FAKE_HASH
    assert m_auto["dirty_llm_loop"] is True and m_wt["dirty_llm_loop"] is False
    assert m_rel["mode"] == "release" and m_rel["llm_loop_path"] == str(rel_ll)


# ── 集成：CLI 校验 + 真实 main() 证据行/meta/report ──────────────────────


def test_cli_rejects_unknown_code_source() -> None:
    with pytest.raises(SystemExit) as ei:
        run_eval.main(["--code-source", "bogus", "--dry"])
    assert ei.value.code == 2


def _install_fakes(monkeypatch: pytest.MonkeyPatch, seen_meta: list[dict]) -> dict:
    """真实评测集缩成 1 场景 1 样本；evaluate 记录收到的 code_source 后返回同形输出."""
    real = json.loads((_REPO / "tests" / "eval_sets" / "scenarios_v1.json").read_text(encoding="utf-8"))
    sc = dict(real["scenarios"][0])
    sc["samples"] = 1
    scenarios = {"name": "fake-suite", "version": "v-fake", "scenarios": [sc]}

    def fake_evaluate(scenarios: dict, **kwargs: object) -> dict:
        seen_meta.append(dict(kwargs["code_source"]))  # type: ignore[arg-type]
        return {
            "dry": True,
            "heldout_sealed": False,
            "code_source": kwargs["code_source"],
            "budget": {
                "profile": "product",
                "base": 500,
                "product_default": 500,
                "pins_honored": True,
                "scenario_pins": {},
                "effective_by_scenario": {"s1": 500},
            },
            "results": [
                {
                    "id": "s1",
                    "name": "S1",
                    "verdict": sc["verdict"],
                    "samples": 1,
                    "passed": 1,
                    "truncated": 0,
                    "failed": 0,
                    "scored": 1,
                    "tokens": {"total_in": 0, "total_out": 0, "avg_per_sample": 0},
                    "rate": 1.0,
                    "rate_scored": 1.0,
                    "truncated_rate": 0.0,
                    "ci": [0.0, 1.0],
                    "ci_scored": [0.0, 1.0],
                    "samples_detail": [],
                }
            ],
        }

    monkeypatch.setattr(run_eval, "load_scenarios", lambda _p: scenarios)
    monkeypatch.setattr(run_eval, "evaluate", fake_evaluate)
    return scenarios


def test_main_auto_evidence_line_and_meta(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """真实 main()（auto+dry，R6 零 LLM 路径）：stderr 证据行 + meta 入 report + md 渲染一行."""
    seen: list[dict] = []
    _install_fakes(monkeypatch, seen)
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--dry", "--output", str(tmp_path / "out")])

    assert run_eval.main() == 0

    err = capsys.readouterr().err
    assert "[code-source] mode=auto llm_loop=" in err, "auto 必打证据行（R1/R6）"
    assert f"head={run_eval.git_head_short()}" in err or "head=" in err

    assert seen, "evaluate 必须收到 code_source meta"
    cs = seen[0]
    assert cs["mode"] == "auto" and set(cs) == {
        "mode", "llm_loop_path", "release_hash", "repo_head", "dirty_llm_loop"
    }
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["code_source"] == cs, "meta 与 knowledge_store 同级入 report（R5）"
    md = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "> code-source: mode=auto" in md and "dirty_llm_loop=" in md, "md 渲染一行（R5）"
