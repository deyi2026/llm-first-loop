"""run_eval 知识库状态显式化（2026-10-25）：empty/snapshot 绑定 + 样本隔离.

零 LLM 零网络：用例 1-6 不 build_engine，直测 run_eval 的绑定三件套
（prepare_knowledge_binding / per_sample_knowledge / bound_runtime_paths）；
用例 7（E1' P2 修复轮新增）真实 build_engine 端到端（不起 run → 不调 LLM）。
- 环境哨兵：EXPERIENCES_DIR/METHODS_DIR 指向含 canary 的假生产目录时，
  注入的 RuntimePaths 仍落样本 tmp，canary 未被读取/拷贝/改写
- empty：样本级 knowledge/{experiences,methods} 存在且 0 文件
- snapshot：快照与源 fixture 文件数一致；样本副本写入不污染快照/源
- 两样本副本 inode 不同（真拷贝非硬链接）、A 的写入不出现在 B
- RuntimePaths.data_dir == <sample>/data（样本自己，不跨样本共享）
- CLI 拒绝 production（parser.error 提示改用 snapshot）

载入方式与 tests/scripts/test_run_eval_scratch.py 一致（sys.path 注入 scripts/）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import run_eval  # noqa: E402  — scripts 层模块（sys.path 注入后导入）


def _mk_sources(root: Path) -> tuple[Path, Path]:
    exp = root / "experiences"
    methods = root / "data" / "methods"
    (exp / "grp").mkdir(parents=True)
    (exp / "grp" / "a.md").write_text("exp-a", encoding="utf-8")
    methods.mkdir(parents=True)
    (methods / "b.md").write_text("method-b", encoding="utf-8")
    return exp, methods


def _files_under(p: Path) -> set[str]:
    return {str(q.relative_to(p)) for q in p.rglob("*") if q.is_file()}


# ── 1. env 哨兵：显式注入对 os.environ 指向的“假生产目录”免疫 ──────────


def test_env_sentinel_canary_untouched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """EXPERIENCES_DIR/METHODS_DIR 指向含 canary 的目录：解析仍落样本 tmp，canary 不被读写."""
    fake_prod = tmp_path / "prod"
    canary_exp = fake_prod / "experiences" / "CANARY.md"
    canary_m = fake_prod / "data" / "methods" / "CANARY.md"
    canary_exp.parent.mkdir(parents=True)
    canary_m.parent.mkdir(parents=True)
    canary_exp.write_text("exp-canary", encoding="utf-8")
    canary_m.write_text("method-canary", encoding="utf-8")
    monkeypatch.setenv("EXPERIENCES_DIR", str(canary_exp.parent))
    monkeypatch.setenv("METHODS_DIR", str(canary_m.parent))

    sources = _mk_sources(tmp_path / "src")
    run_scratch = tmp_path / "scratch"
    run_scratch.mkdir()
    binding = run_eval.prepare_knowledge_binding(run_scratch, "snapshot", sources)
    sample = tmp_path / "sample"
    sample.mkdir()
    rp = run_eval.per_sample_knowledge(binding, sample)

    assert str(rp.experiences_dir).startswith(str(sample / "knowledge"))
    assert str(rp.methods_dir).startswith(str(sample / "knowledge"))
    assert not list((sample / "knowledge").rglob("CANARY*")), "canary 不得被拷进样本副本"
    assert not list((run_scratch / "knowledge-snapshot").rglob("CANARY*")), "canary 不得被拷进快照"
    assert canary_exp.read_text(encoding="utf-8") == "exp-canary"
    assert canary_m.read_text(encoding="utf-8") == "method-canary"


# ── 2. empty 模式 ────────────────────────────────────────────────────────


def test_empty_mode_zero_files(tmp_path: Path) -> None:
    run_scratch = tmp_path / "scratch"
    run_scratch.mkdir()
    binding = run_eval.prepare_knowledge_binding(run_scratch, "empty")
    assert binding["mode"] == "empty"
    assert binding["files"] == 0

    sample = tmp_path / "sample"
    sample.mkdir()
    rp = run_eval.per_sample_knowledge(binding, sample)
    exp = sample / "knowledge" / "experiences"
    methods = sample / "knowledge" / "methods"
    assert exp.is_dir() and methods.is_dir()
    assert len(_files_under(exp)) == 0
    assert len(_files_under(methods)) == 0
    assert rp.experiences_dir == exp
    assert rp.methods_dir == methods


# ── 3. snapshot：拷贝保真 + 写入不回流 ───────────────────────────────────


def test_snapshot_copy_and_no_writeback(tmp_path: Path) -> None:
    src_exp, src_methods = _mk_sources(tmp_path / "src")
    run_scratch = tmp_path / "scratch"
    run_scratch.mkdir()
    binding = run_eval.prepare_knowledge_binding(run_scratch, "snapshot", (src_exp, src_methods))
    snap_exp = Path(binding["experiences"])
    snap_methods = Path(binding["methods"])
    assert _files_under(snap_exp) == _files_under(src_exp)
    assert _files_under(snap_methods) == _files_under(src_methods)
    assert binding["files"] == 2

    sample = tmp_path / "sample"
    sample.mkdir()
    rp = run_eval.per_sample_knowledge(binding, sample)
    assert _files_under(sample / "knowledge" / "experiences") == _files_under(src_exp)
    assert rp.experiences_dir == sample / "knowledge" / "experiences"

    # 样本副本写入：run 级快照与源 fixture 都不得变化
    new_file = sample / "knowledge" / "experiences" / "grp" / "new.md"
    new_file.write_text("sample-write", encoding="utf-8")
    assert not (snap_exp / "grp" / "new.md").exists(), "run 级快照不得被样本写入污染"
    assert not (src_exp / "grp" / "new.md").exists(), "源 fixture 不得被样本写入污染"


# ── 4. 两样本隔离：真副本（inode 不同）且写入互不可见 ─────────────────────


def test_two_samples_isolated(tmp_path: Path) -> None:
    sources = _mk_sources(tmp_path / "src")
    run_scratch = tmp_path / "scratch"
    run_scratch.mkdir()
    binding = run_eval.prepare_knowledge_binding(run_scratch, "snapshot", sources)
    sa, sb = tmp_path / "sampleA", tmp_path / "sampleB"
    sa.mkdir()
    sb.mkdir()
    run_eval.per_sample_knowledge(binding, sa)
    run_eval.per_sample_knowledge(binding, sb)

    fa = sa / "knowledge" / "experiences" / "grp" / "a.md"
    fb = sb / "knowledge" / "experiences" / "grp" / "a.md"
    assert os.stat(fa).st_ino != os.stat(fb).st_ino, "两样本副本 inode 必须不同（真拷贝，非硬链接）"

    (sa / "knowledge" / "methods" / "A_ONLY.md").write_text("A", encoding="utf-8")
    assert not (sb / "knowledge" / "methods" / "A_ONLY.md").exists(), "A 的写入不得出现在 B"


# ── 5. RuntimePaths.data_dir 指向样本自己的 data ─────────────────────────


def test_runtime_paths_data_dir_per_sample(tmp_path: Path) -> None:
    run_scratch = tmp_path / "scratch"
    run_scratch.mkdir()
    binding = run_eval.prepare_knowledge_binding(run_scratch, "empty")
    sample = tmp_path / "sampleX"
    sample.mkdir()
    rp = run_eval.per_sample_knowledge(binding, sample)
    assert rp.data_dir == sample / "data"
    assert rp.experiences_source == "eval_binding"
    assert rp.methods_source == "eval_binding"


# ── 6. CLI 拒绝 production ───────────────────────────────────────────────


def test_cli_rejects_production(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as ei:
        run_eval.main(["--knowledge-store", "production", "--dry"])
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert "production" in err
    assert "snapshot" in err


# ── 7. build_engine 端到端：绑定注入后 store/retriever 全部落样本 tmp ────


def test_build_engine_binding_end_to_end(tmp_path: Path) -> None:
    """真实 build_engine（零 LLM、零网络、不起 run）：注入的 runtime_paths 决定
    MethodStore/ExperienceStore/semantic 检索器 method/experience/rerank 三个缓存
    目录全部落样本 tmp，且 RuntimePaths.data_dir == Settings.data_dir == <sample>/data。

    内部对象取法照抄独立审核探针 work/review-e1p-probe.py（gc.get_objects 差分 +
    MethodStore._dir / ExperienceStore 的 vars() Path / SemanticRetriever 的
    _method_cache_path 等私有属性），只做只读观察，不改产品代码。
    """
    import gc

    from llm_loop.experiences.store import ExperienceStore
    from llm_loop.factory import build_engine
    from llm_loop.memory.retriever import SemanticRetriever
    from llm_loop.methods.store import MethodStore

    def _build_once(sample: Path, binding: dict):
        """绑定 → Settings._extra 注入 → 真实 build_engine，返回 (rp, settings, 新对象)."""
        rp = run_eval.per_sample_knowledge(binding, sample)
        settings = run_eval._settings(sample, "probe-key")
        settings._extra["runtime_paths"] = rp
        before = {id(o) for o in gc.get_objects()
                  if isinstance(o, (MethodStore, ExperienceStore, SemanticRetriever))}
        engine = build_engine(settings)  # type: ignore[arg-type]
        assert engine is not None, "build_engine 应成功（不调 run → 不起 LLM）"
        fresh = {
            "method": [o for o in gc.get_objects()
                       if isinstance(o, MethodStore) and id(o) not in before],
            "experience": [o for o in gc.get_objects()
                           if isinstance(o, ExperienceStore) and id(o) not in before],
            "retriever": [o for o in gc.get_objects()
                          if isinstance(o, SemanticRetriever) and id(o) not in before],
        }
        return rp, settings, fresh

    # ── snapshot：小 fixture 源（不依赖真实生产目录）──
    src_exp, src_methods = _mk_sources(tmp_path / "src")
    run_scratch = tmp_path / "scratch"
    run_scratch.mkdir()
    binding = run_eval.prepare_knowledge_binding(run_scratch, "snapshot", (src_exp, src_methods))
    sample = tmp_path / "sample-snap"
    sample.mkdir()
    rp, settings, fresh = _build_once(sample, binding)

    assert len(fresh["method"]) == 1, f"新 MethodStore 应恰 1 个，实际 {len(fresh['method'])}"
    assert len(fresh["experience"]) == 1, (
        f"新 ExperienceStore 应恰 1 个，实际 {len(fresh['experience'])}"
    )
    ms_dir = Path(fresh["method"][0]._dir).resolve()
    assert ms_dir == rp.methods_dir.resolve(), f"MethodStore._dir 应落样本 methods：{ms_dir}"
    es_paths = {str(v) for v in vars(fresh["experience"][0]).values() if isinstance(v, Path)}
    assert any(Path(v).resolve() == rp.experiences_dir.resolve() for v in es_paths), (
        f"ExperienceStore 应落样本 experiences：paths={sorted(es_paths)[:3]}"
    )

    assert fresh["retriever"], "semantic 检索器必须存在（降级壳也算）"
    ret = fresh["retriever"][0]
    mc = getattr(ret, "_method_cache_path", None)
    ec = getattr(ret, "_experience_cache_path", None)
    rc = getattr(ret, "_rerank_cache_path", None)
    assert mc is not None and Path(mc).parent.resolve() == rp.methods_dir.resolve(), (
        f"retriever method 缓存应落样本 methods：{mc}"
    )
    assert ec is not None and Path(ec).parent == rp.data_dir / "experience-embeddings", (
        f"retriever experience 缓存应落样本 data/experience-embeddings：{ec}"
    )
    assert rc is not None and Path(rc).parent == rp.data_dir / "semantic-rerank-embeddings", (
        f"retriever rerank 缓存应落样本 data/semantic-rerank-embeddings：{rc}"
    )

    # data_dir 三方一致：RuntimePaths == Settings == <sample>/data
    assert rp.data_dir == sample / "data"
    assert str(rp.data_dir) == settings.data_dir, (
        f"settings.data_dir 应等于 RuntimePaths.data_dir：{settings.data_dir}"
    )

    # ── empty 模式再来一轮：目录存在、零文件 ──
    binding_empty = run_eval.prepare_knowledge_binding(tmp_path / "scratch-empty", "empty")
    sample_e = tmp_path / "sample-empty"
    sample_e.mkdir()
    rp_e, settings_e, fresh_e = _build_once(sample_e, binding_empty)
    assert len(fresh_e["method"]) == 1 and len(fresh_e["experience"]) == 1
    assert rp_e.experiences_dir.is_dir() and rp_e.methods_dir.is_dir()
    assert len(_files_under(rp_e.experiences_dir)) == 0, "empty 模式样本 experiences 必须 0 文件"
    assert len(_files_under(rp_e.methods_dir)) == 0, "empty 模式样本 methods 必须 0 文件"
    assert rp_e.data_dir == sample_e / "data"
    assert str(rp_e.data_dir) == settings_e.data_dir

