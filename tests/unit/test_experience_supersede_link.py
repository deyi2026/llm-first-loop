"""T0-C1: 写时近重复无损链接（link-not-merge）+ 检索端 supersede 去重单测."""
from __future__ import annotations

from pathlib import Path

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore


class KeywordVecEmbedder:
    """确定性 stub: 按 marker 子串给向量; marker A→[1,0], B→[0,1]; 无 marker→None."""

    provider = "stub"
    vector_version = "stub-v1"

    def embed(self, text: str):
        if "重启残留" in text:
            return [1.0, 0.0]
        if "记忆聚类" in text:
            return [0.0, 1.0]
        return None


def _doc(title: str, scenario: str) -> ExperienceDocument:
    return ExperienceDocument(
        title=title,
        scenario=scenario,
        root_cause="同因",
        solution="同解",
        evidence="ev",
        tags=["t"],
        source={"type": "unit"},
    )


def test_write_near_dup_links_not_merges(tmp_path: Path):
    store = ExperienceStore(tmp_path, embedder=KeywordVecEmbedder())
    f1 = store.save(_doc("restart-env-residue-v1", "重启残留 场景甲"))
    f2 = store.save(_doc("restart-env-residue-v2", "重启残留 场景甲改动"))
    # 旧条目不被改写
    d1 = store.get(f1)
    assert d1 is not None and d1.supersedes == []
    assert d1.title == "restart-env-residue-v1"
    # 新条目带反向链接（无损）
    d2 = store.get(f2)
    assert d2 is not None and d1 and (f1.removesuffix(".md") in d2.supersedes)
    # 文件 front matter round-trip
    raw = (tmp_path / f2).read_text(encoding="utf-8")
    assert "supersedes:" in raw


def test_retrieval_returns_latest_canonical_only(tmp_path: Path):
    store = ExperienceStore(tmp_path, embedder=KeywordVecEmbedder())
    f1 = store.save(_doc("restart-env-residue-a1", "重启残留 甲"))
    store.save(_doc("restart-env-residue-a2", "重启残留 甲"))
    f3 = store.save(_doc("cluster-report", "记忆聚类 语料"))
    # 语义/词法命中近重复族 → 只有最新; 无关条目不受影响
    records = store.list_active("重启残留")
    ids = [r["file"] for r in records]
    assert f1 not in ids
    assert len([i for i in ids if "restart-env-residue" in i]) == 1
    # 无关条目不受影响（catalog 断言覆盖; 近重复查询本就不应命中它）
    # 空 query catalog 同样只列 canonical + 无关
    catalog_ids = {r["file"] for r in store.list_active("")}
    assert f1 not in catalog_ids and f3 in catalog_ids


def test_fifteen_rewrite_chain_collapses_to_newest(tmp_path: Path):
    store = ExperienceStore(tmp_path, embedder=KeywordVecEmbedder())
    newest = ""
    for i in range(15):
        newest = store.save(_doc(f"restart-env-residue-r{i}", "重启残留 同一教训"))
    records = store.list_active("重启残留")
    hit = [r for r in records if "restart-env-residue" in r["file"]]
    assert len(hit) == 1 and hit[0]["file"] == newest
    # 链是增量无损: 每版只指向前一版（cap 内）
    d = store.get(newest)
    assert d is not None and len(d.supersedes) >= 1


def test_no_embedder_or_failure_never_blocks_save(tmp_path: Path):
    store = ExperienceStore(tmp_path)  # 无 embedder
    f = store.save(_doc("no-embedder-case", "普通场景"))
    d = store.get(f)
    assert d is not None and d.supersedes == []

    class Boom(KeywordVecEmbedder):
        def embed(self, text: str):
            raise RuntimeError("8765 down")

    store2 = ExperienceStore(tmp_path / "b", embedder=Boom())
    f2 = store2.save(_doc("embedder-down-case", "重启残留 但服务不可用"))
    d2 = store2.get(f2)
    assert d2 is not None and d2.supersedes == []
