"""多查询融合影子探针（REPORT-20260924）：旁路测量零行为变化 + JSONL 记录契约."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_loop.memory.multiquery_shadow import (
    MultiqueryShadowProbe,
    _parse_variants,
    make_llm_rewriter,
    rrf_fuse,
)


class _TmpProbe:
    @pytest.fixture()
    def probe_with_log(self, tmp_path):
        log = tmp_path / "shadow.jsonl"

        def make(rewriter):
            return MultiqueryShadowProbe(rewriter=rewriter, out_path=log), log

        return make


class TestProbe:
    def test_run_writes_jsonl(self, tmp_path):
        log = tmp_path / "shadow.jsonl"
        probe = MultiqueryShadowProbe(
            rewriter=lambda q: [q + " v1", q + " v2"], out_path=log
        )
        calls = []

        def search_fn(text):
            calls.append(text)
            return ["B", "A"] if "v1" in text else ["C", "A", "B"]

        rec = probe.run(
            "查询", 10, "sess-1", search_fn, primary_ids=["A", "D", "E"]
        )
        assert rec is not None and rec["n_variants"] == 2
        assert len(calls) == 2  # 每变体恰好一次检索
        assert rec["overlap_at_5"] == len({"A", "D", "E"} & set(rec["fused_top"][:5]))
        assert rec["latency"]["total_s"] >= rec["latency"]["search_s"] >= 0
        assert rec["primary_top1_in_fused_top1"] in (True, False)
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["query"] == "查询"

    def test_rewriter_error_recorded_not_raised(self, tmp_path):
        log = tmp_path / "shadow.jsonl"

        def boom(_q):
            raise RuntimeError("network down")

        probe = MultiqueryShadowProbe(rewriter=boom, out_path=log)
        rec = probe.run("查询", 5, "", lambda t: [], primary_ids=["X"])
        assert rec is not None and "RuntimeError" in rec["error"]
        assert json.loads(log.read_text(encoding="utf-8").strip())["error"]

    def test_disabled_without_rewriter(self, tmp_path):
        probe = MultiqueryShadowProbe(out_path=tmp_path / "x.jsonl")
        assert not probe.enabled
        assert probe.run("q", 5, "", lambda t: [], primary_ids=[]) is None

    def test_empty_query_skipped(self):
        probe = MultiqueryShadowProbe(rewriter=lambda q: ["a"])
        assert probe.run("   ", 5, "", lambda t: [], primary_ids=[]) is None


class TestFuseAndParse:
    def test_rrf_fuse_equal_weight(self):
        fused = rrf_fuse([["A", "B"], ["B", "C"]])
        assert fused[0] == "B"  # 两列表共识第一

    def test_parse_variants_json(self):
        assert _parse_variants('["a b", "c"]') == ["a b", "c"]

    def test_parse_variants_garbage(self):
        assert _parse_variants("变体一，变体二") == ["变体一", "变体二"]
        assert _parse_variants("") == []

    def test_make_llm_rewriter(self):
        class _Resp:
            content = '["飞书 凭证 加载", "feishu bridge credentials"]'

        class _Llm:
            def chat(self, messages, tools, *, timeout_s=None, **_kw):
                assert timeout_s == 10.0 and tools == []
                return _Resp()

        rw = make_llm_rewriter(_Llm())
        assert rw("飞书桥密钥从哪加载") == ["飞书 凭证 加载", "feishu bridge credentials"]


class TestSearcherIntegration:
    """RecordSearcher 影子挂点：返回值逐字节一致 + 变体检索走 _skip_shadow 无递归."""

    @staticmethod
    def _make_searcher(probe=None):
        from llm_loop.introspection.search import RecordSearcher

        class _Entry:
            def __init__(self, eid, content):
                self.id, self.content = eid, content
                self.created_at, self.keywords = "2026-09-24", []
                self.scope, self.source_session_id = "global", ""

        class _Mem:
            def __init__(self):
                self.entries = [
                    _Entry("MEM-1", "飞书桥凭证 restart_system.sh 加载顺序"),
                    _Entry("MEM-2", "检索融合 RRF 排序实验"),
                ]

            def all(self):
                return self.entries

            def search(self, words, top_k=10, session_id=""):
                return [e for e in self.entries if any(w in e.content for w in words)][:top_k]

            def _by_id(self, eid):
                return next((e for e in self.entries if e.id == eid), None)

        class _Result:
            def __init__(self, entries, mode="fused"):
                self.entries, self.mode, self.note = entries, mode, ""

        class _Sem:
            def __init__(self):
                self.variant_calls = 0

            def semantic_available(self):
                return True

            def search(self, query, top_k=10, scope="memory", session_id="", memory=None, keyword_results=None):
                if query.startswith("变体"):
                    self.variant_calls += 1
                base = list(keyword_results or [])
                base += [{"kind": "memory", "ts": "", "id": e.id, "summary": e.content,
                          "file": "memory/index.json", "key": f"memory:{e.id}"}
                         for e in memory.entries if e.id not in {h.get("id") for h in base}]
                return _Result(base[:top_k])

        sem = _Sem()
        searcher = RecordSearcher(
            audit_dir="/tmp", memory_store=_Mem(), semantic_retriever=sem, multiquery_shadow=probe
        )
        return searcher, sem

    def test_shadow_on_off_identical_returns(self, tmp_path):
        log = tmp_path / "s.jsonl"
        probe = MultiqueryShadowProbe(rewriter=lambda q: ["变体一", "变体二"], out_path=log)
        with_probe, sem1 = self._make_searcher(probe)
        without_probe, _ = self._make_searcher(None)

        a = with_probe._search_memory("飞书 凭证", 10, session_id="s1")
        b = without_probe._search_memory("飞书 凭证", 10, session_id="s1")
        assert a == b  # 影子模式零行为变化

        rows = [json.loads(x) for x in log.read_text(encoding="utf-8").strip().splitlines()]
        assert len(rows) == 1 and rows[0]["n_variants"] == 2
        assert sem1.variant_calls == 2  # 2 变体各检索一次，且未递归（否则远超 2）

    def test_no_probe_by_default(self):
        searcher, _ = self._make_searcher(None)
        assert getattr(searcher, "_multiquery_shadow", None) is None
        assert searcher._search_memory("飞书", 10)  # off 路径原样工作


class TestConfigMode:
    def test_env_modes(self, monkeypatch):
        from llm_loop.config import load_settings

        for val, expect in (("shadow", "shadow"), ("off", "off"), ("bogus", "off")):
            monkeypatch.setenv("LLM_API_KEY", "k")
            monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
            monkeypatch.setenv("LLM_MODEL", "m")
            monkeypatch.setenv("RETRIEVAL_MULTIQUERY_MODE", val)
            monkeypatch.delenv("DATA_DIR", raising=False)
            assert load_settings().retrieval_multiquery_mode == expect

    def test_default_off(self, monkeypatch):
        from llm_loop.config import load_settings

        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.setenv("LLM_BASE_URL", "https://x/v1")
        monkeypatch.setenv("LLM_MODEL", "m")
        monkeypatch.delenv("RETRIEVAL_MULTIQUERY_MODE", raising=False)
        monkeypatch.delenv("DATA_DIR", raising=False)
        assert load_settings().retrieval_multiquery_mode == "off"
