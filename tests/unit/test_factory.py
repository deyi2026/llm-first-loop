"""单元测试: factory 装配（M17 FR-REVIEW-AI-05 evolution_summary 闭包）.

覆盖: architecture_config 含 evolution_summary（total/pending_review/executing/recent）；
文件不存在 → 全 0 摘要；store.list 抛 OSError → error 字段如实标注（fail-open）；
既有 config 维度零变化。
"""

from __future__ import annotations

from unittest import mock

from llm_loop.config import Settings


def _settings(tmp_path) -> Settings:
    return Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        self_inspection_enabled=True,  # architecture_status 可用
        extract_enabled=False,
    )


def test_evolution_summary_present(tmp_path):
    """architecture_config 含 evolution_summary（total/pending_review/executing/recent）."""
    from llm_loop.factory import build_engine

    settings = _settings(tmp_path)
    engine = build_engine(settings)  # type: ignore[arg-type]
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    store.transition(sug.id, status="executing")
    # architecture_status 拉取 architecture_config 维度
    snap = engine.status.snapshot(dimensions=["architecture_config"])
    cfg = snap.get("architecture_config", {})
    assert "evolution_summary" in cfg
    es = cfg["evolution_summary"]
    assert es["total"] == 1
    assert es["executing"] == 1
    assert es["recent"] and es["recent"][0]["id"] == sug.id
    # 既有 config 维度保留
    assert "evolve_local_exec" in cfg
    assert "self_eval_enabled" in cfg


def test_evolution_summary_empty_dir(tmp_path):
    """无建议文件 → 全 0 摘要（不报错）."""
    from llm_loop.factory import build_engine

    settings = _settings(tmp_path)
    engine = build_engine(settings)  # type: ignore[arg-type]
    snap = engine.status.snapshot(dimensions=["architecture_config"])
    es = snap.get("architecture_config", {}).get("evolution_summary", {})
    assert es.get("total") == 0
    assert es.get("executing") == 0
    assert "error" not in es


def test_evolution_summary_read_fail_open(tmp_path):
    """store.list 抛 OSError → evolution_summary.error 字段如实标注（fail-open 不抛穿）."""
    from llm_loop.factory import _build_config_status_with_evolution

    settings = _settings(tmp_path)
    cfg_fn = _build_config_status_with_evolution(settings)
    with mock.patch(
        "llm_loop.introspection.evolution.EvolutionStore.list", side_effect=OSError("read fail")
    ):
        cfg = cfg_fn()
    es = cfg.get("evolution_summary", {})
    assert "error" in es
    assert "读取失败" in es["error"]
    assert "search_records(kind=evolution)" in es["note"]
    # 既有 config 维度不受影响（fail-open 不抛穿）
    assert cfg.get("evolve_local_exec") == 0
