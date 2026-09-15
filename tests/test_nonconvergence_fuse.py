"""EVO-20260915-789eb9d5 纯机械非收敛熔断守卫单测（零模型依赖）."""
from __future__ import annotations

import types

from llm_loop.core.loop.engine_services.interrupted_capture import InterruptedCapture
from llm_loop.core.loop.engine_services.nonconvergence_guard import (
    NonconvergenceFuseError,
    NonconvergenceGuard,
)
from llm_loop.llm.errors import LLMError

SENT = "我需要先检查配置文件 然后再核对依赖版本 我需要先检查配置文件 然后再核对依赖版本"
OTHER = "继续推进任务清单：先读设计文档，再定位实现文件，最后补测试用例并跑回归"


def _feed(guard, blocks, *, drafts=None, persists=None):
    drafts = drafts if drafts is not None else [0] * len(blocks)
    persists = persists if persists is not None else [0] * len(blocks)
    full = ""
    for text, dcount, pseq in zip(blocks, drafts, persists):
        full += text
        guard.observe_checkpoint(
            reasoning_chars=len(full),
            reasoning_full=full,
            tool_draft_count=dcount,
            persist_seq=pseq,
        )


def _guard(**kw):
    kw.setdefault("windows", 3)
    kw.setdefault("min_delta_tokens", 2)
    return NonconvergenceGuard(**kw)


def test_trips_after_three_repeat_windows():
    g = _guard()
    _feed(g, [SENT, SENT, SENT, SENT])
    assert g.tripped is True
    assert g.evidence["streak"] == 3
    assert g.evidence["jaccard"] == 1.0


def test_not_trips_on_novel_reasoning():
    g = _guard()
    _feed(g, [SENT, OTHER, SENT + OTHER, OTHER * 2, SENT * 2])
    assert g.tripped is False


def test_new_draft_resets_streak():
    g = _guard()
    _feed(g, [SENT, SENT, SENT, SENT], drafts=[0, 0, 1, 0])
    assert g.tripped is False
    assert g.last_window.qualifies is True  # 末窗口重新合格但连击=1


def test_persist_write_resets_streak():
    g = _guard()
    _feed(g, [SENT, SENT, SENT, SENT], persists=[0, 0, 1, 1])
    assert g.tripped is False


def test_no_reasoning_growth_no_trip():
    g = _guard()
    _feed(g, [SENT, "", SENT, "", SENT])
    assert g.tripped is False


def test_disabled_by_windows_zero():
    g = _guard(windows=0)
    _feed(g, [SENT] * 6)
    assert g.tripped is False


def test_from_env_disable(monkeypatch):
    monkeypatch.setenv("LFL_NONCONV_FUSE_WINDOWS", "0")
    assert NonconvergenceGuard.from_env().windows == 0
    monkeypatch.setenv("LFL_NONCONV_FUSE_WINDOWS", "2")
    monkeypatch.setenv("LFL_NONCONV_FUSE_JACCARD", "0.9")
    monkeypatch.setenv("LFL_NONCONV_FUSE_MIN_DELTA", "4")
    g = NonconvergenceGuard.from_env()
    assert (g.windows, g.jaccard_threshold, g.min_delta_tokens) == (2, 0.9, 4)


def test_error_is_llmerror_with_evidence():
    err = NonconvergenceFuseError({"streak": 3, "jaccard": 1.0})
    assert isinstance(err, LLMError)
    assert err.evidence["streak"] == 3
    assert "nonconvergence_fuse" in str(err)


class _FakeEngine:
    def __init__(self):
        self.checkpoints = []
        self.interrupted = []
        self.journal = types.SimpleNamespace(receipt_commit_count=0)

    def _tool_execution_journal(self):
        return self.journal

    def _on_llm_partial_checkpoint(self, sess, **kw):
        self.checkpoints.append(kw)

    def _on_llm_interrupted(self, sess, *, reason, **kw):
        self.interrupted.append(reason)


class _Delta:
    def __init__(self, text="", reasoning=""):
        self.text = text
        self.reasoning = reasoning


def test_capture_fuse_end_to_end(monkeypatch):
    monkeypatch.setenv("LFL_NONCONV_FUSE_WINDOWS", "3")
    monkeypatch.setenv("LFL_NONCONV_FUSE_MIN_DELTA", "2")
    eng = _FakeEngine()
    sess = types.SimpleNamespace(session_id="s1")
    cap = InterruptedCapture(eng, sess=sess, round_no=1, provider="p", model="m")
    cap.mark_provider_send()
    chunk = SENT * 80  # >1024 chars/块，绕过 checkpoint 节流
    for _ in range(4):
        cap.on_delta(_Delta(reasoning=chunk))
    assert cap.fuse_tripped is True
    assert len(eng.checkpoints) == 4  # 基线 + 3 个合格窗口
    assert cap.fuse_evidence["streak"] == 3
    cap.fire(sess, "nonconvergence_fuse", 1)
    assert eng.interrupted == ["nonconvergence_fuse"]


def test_capture_disabled_by_env(monkeypatch):
    monkeypatch.setenv("LFL_NONCONV_FUSE_WINDOWS", "0")
    eng = _FakeEngine()
    sess = types.SimpleNamespace(session_id="s2")
    cap = InterruptedCapture(eng, sess=sess, round_no=1)
    cap.mark_provider_send()
    for _ in range(6):
        cap.on_delta(_Delta(reasoning=SENT * 80))
    assert cap.fuse_tripped is False
