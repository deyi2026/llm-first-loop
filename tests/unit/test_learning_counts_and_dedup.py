"""Learning 面板 counts 全历史口径 + reflection 防重复门（2026-09-24）.

改进 A：counts.saved 不再随 recent_jobs 窗口滚动回退（terminal 单调累计）。
改进 B：reflection payload 注入 existing_methods（active/qualified 摘要）+
system 指令 dup 短路，防止语义重复卡重复产 token。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from llm_loop.methods.learning_journal import LearningJournal


def _mk(tmp_path: Path) -> LearningJournal:
    return LearningJournal(tmp_path / "learning_journal.jsonl", max_attempts=2)


def test_count_states_all_history_beyond_recent_window(tmp_path: Path) -> None:
    """saved 出 recent_jobs 窗口后 count_states 仍计入（面板不再倒数）。"""
    journal = _mk(tmp_path)
    for i in range(4):
        job = journal.enqueue(f"episode:s1:{i}:e{i}", session_id="s1")
        assert job is not None
        journal.mark_saved(job.job_id, f"method:probe-{i}")
    recent = journal.recent_jobs(limit=2)
    assert len(recent) == 2, "窗口只保留最近 2 条"
    counts = journal.count_states()
    assert counts.get("saved") == 4, "全历史口径必须计入已滚出窗口的 saved"


def test_count_states_counts_inflight_and_terminal(tmp_path: Path) -> None:
    """queued（在飞）与 saved/none（终态）同折计数。"""
    journal = _mk(tmp_path)
    a = journal.enqueue("episode:s1:1:a", session_id="s1")
    b = journal.enqueue("episode:s1:2:b", session_id="s1")
    c = journal.enqueue("episode:s1:3:c", session_id="s1")
    assert a and b and c
    journal.mark_none(c.job_id, "no reusable method")
    counts = journal.count_states()
    assert counts.get("queued") == 2
    assert counts.get("none") == 1


def test_learning_status_counts_use_all_history(tmp_path: Path) -> None:
    """/learning/status 的 counts 走 count_states：jobs 窗口 1 条但 saved=2。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from llm_loop.web.routes import router

    journal = _mk(tmp_path)
    first = journal.enqueue("episode:s1:1:old", session_id="s1")
    second = journal.enqueue("episode:s1:2:new", session_id="s1")
    assert first and second
    journal.mark_saved(first.job_id, "method:old")
    journal.mark_saved(second.job_id, "method:new")

    app = FastAPI()
    app.state.engine = SimpleNamespace(
        learning_journal=journal,
        learning_plane=None,
        settings=SimpleNamespace(
            data_dir=str(tmp_path), learning_plane_enabled=True
        ),
    )
    app.include_router(router)
    payload = TestClient(app).get("/api/v1/learning/status?limit=1").json()
    assert len(payload["jobs"]) == 1
    assert payload["counts"].get("saved") == 2, "counts 必须是全历史口径"


def test_reflection_payload_carries_existing_methods_gate() -> None:
    """existing_methods 只含 active/qualified 卡；system 含 dup 短路指令。"""
    from llm_loop.methods import reflection as refl

    class _Store:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get(self, ref: str):  # core method stub
            return SimpleNamespace(body="core body")

        def list(self, query: str = "", limit: int = 20):
            self.calls.append(query)
            return [
                {"id": "active-one", "status": "active", "description": "d1"},
                {"id": "qual-two", "status": "qualified", "description": "d2"},
                {"id": "cand-three", "status": "candidate", "description": "d3"},
                {"id": "hold-four", "status": "hold", "description": "d4"},
            ]

    store = _Store()
    briefs = refl._existing_method_briefs(store)  # type: ignore[arg-type]
    joined = "\n".join(briefs)
    assert "active-one" in joined and "qual-two" in joined
    assert "cand-three" not in joined and "hold-four" not in joined


def test_reflection_briefs_fail_open_on_store_error() -> None:
    """store.list 抛异常 → 空清单（反思照常，fail-open）。"""
    from llm_loop.methods import reflection as refl

    class _Boom:
        def get(self, ref: str):
            return SimpleNamespace(body="core")

        def list(self, query: str = "", limit: int = 20):
            raise RuntimeError("store unavailable")

    assert refl._existing_method_briefs(_Boom()) == []  # type: ignore[arg-type]
