"""Learning 面板 counts 全历史口径 + reflection 防重复门（2026-09-24）.

改进 A：counts.saved 不再随 recent_jobs 窗口滚动回退（terminal 单调累计）。
改进 B：reflection payload 注入 existing_methods（可检索方法摘要）+
system 指令 dup 短路，防止语义重复卡重复产 token。
"""

from __future__ import annotations

import json
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
    """Candidate methods participate in dedup without a promotion prerequisite."""
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
                {"id": "retired-five", "status": "retired", "description": "d5"},
            ]

    store = _Store()
    briefs = refl._existing_method_briefs(store)  # type: ignore[arg-type]
    joined = "\n".join(briefs)
    assert "active-one" in joined and "qual-two" in joined
    assert "cand-three" in joined and "hold-four" in joined
    assert "retired-five" not in joined


def test_reflection_briefs_reserve_status_coverage_and_obey_character_budget() -> None:
    """A large candidate tail must not evict active/qualified/teacher dedup context."""
    from llm_loop.methods import reflection as refl

    cards = []
    for status, prefix, count in (
        ("candidate", "candidate", 250),
        ("active", "active", 12),
        ("qualified", "qualified", 12),
        ("teacher", "teacher", 3),
        ("hold", "hold", 8),
        ("invalidated", "invalidated", 8),
        ("retired", "retired", 8),
    ):
        for index in range(count):
            cards.append({
                "id": f"{prefix}-{index:03d}",
                "key": f"method:{prefix}-{index:03d}",
                "status": status,
                "description": f"{status} reusable approach " + ("x" * 180),
                "ts": f"2026-10-{(index % 18) + 1:02d}T00:00:00+00:00",
            })

    class _CrowdedStore:
        def __init__(self) -> None:
            self.inventory_calls = 0
            self.list_calls = 0

        def inventory(self, query: str = "", limit: int = 200):
            assert query == ""
            self.inventory_calls += 1
            return {"records": cards[:limit], "counts": {}}

        def list(self, query: str = "", limit: int = 20):
            self.list_calls += 1
            return cards[:limit]

    store = _CrowdedStore()
    briefs = refl._existing_method_briefs(store)  # type: ignore[arg-type]
    joined = "\n".join(briefs)

    assert store.inventory_calls == 1, "brief selection must inspect status-diverse inventory, not the ID-sorted first page"
    assert store.list_calls == 0
    assert "teacher-" in joined
    assert "active-" in joined
    assert "qualified-" in joined
    assert "candidate-" in joined
    assert "retired-000" not in joined
    assert len(briefs) <= 30
    assert len(joined) <= 4800
    assert sum("candidate-" in row for row in briefs) >= 6


def test_reflection_briefs_fail_open_on_store_error() -> None:
    """store.list 抛异常 → 空清单（反思照常，fail-open）。"""
    from llm_loop.methods import reflection as refl

    class _Boom:
        def get(self, ref: str):
            return SimpleNamespace(body="core")

        def list(self, query: str = "", limit: int = 20):
            raise RuntimeError("store unavailable")

    assert refl._existing_method_briefs(_Boom()) == []  # type: ignore[arg-type]


class _ReflectionStore:
    def get(self, ref: str):
        if ref == "method:method-self-distill":
            return SimpleNamespace(body="core body")
        return None

    def list(self, query: str = "", limit: int = 20):
        return [
            {
                "id": "global-active",
                "key": "method:global-active",
                "status": "active",
                "description": "global fallback method",
            }
        ]


class _CaptureClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content='{"decision":"none","reason":"dup:method:restart-check"}')


def _episode() -> dict:
    return {
        "messages": [
            {"role": "user", "content": "重启服务后，怎样确认新进程真的加载了目标代码？", "reasoning_content": "SECRET"},
            {"role": "tool", "content": "pid changed; manifest head=e04172f2"},
            {"role": "assistant", "content": "需要交叉核对进程、manifest 和实际 import provenance。"},
        ]
    }


def test_reflection_method_semantic_related_methods_are_advisory_and_diagnostic() -> None:
    """ON: related_methods 进入 payload；existing_methods 仍保留；diagnostics 可观测。"""
    from llm_loop.methods import reflection as refl

    seen: dict[str, object] = {}

    def discover(query: str, limit: int):
        seen["query"] = query
        seen["limit"] = limit
        return (
            [
                {
                    "id": "restart-check",
                    "key": "method:restart-check",
                    "status": "candidate",
                    "summary": "Verify restarted process provenance",
                    "description": "Cross-check PID, manifest head, and imported module path.",
                    "task_applicability": "not_evaluated",
                }
            ],
            {
                "scope": "method",
                "semantic_requested": True,
                "semantic_effective": True,
                "semantic_fallback_reason": "",
                "semantic_hit_count": 1,
            },
        )

    client = _CaptureClient()
    outcome = refl.reflect_on_episode(
        llm_client=client,
        store=_ReflectionStore(),  # type: ignore[arg-type]
        episode_entry=_episode(),
        trigger_facts={"run_end_reason": "completed", "rounds": 8},
        tool_trace=[],
        run_end_reason="completed",
        final_answer="done",
        method_discovery=discover,
    )

    assert seen["limit"] == 6
    assert "SECRET" not in str(seen["query"])
    assert len(str(seen["query"])) <= 1200
    payload = json.loads(client.calls[0]["messages"][1]["content"])
    assert payload["related_methods"][0]["ref"] == "method:restart-check"
    assert payload["related_methods"][0]["task_applicability"] == "not_evaluated"
    assert "global-active" in "\n".join(payload["existing_methods"])
    assert payload["method_discovery"]["semantic_effective"] is True
    assert outcome.method_discovery_diagnostics["semantic_hit_count"] == 1


def test_reflection_method_semantic_callback_failure_is_fail_open() -> None:
    """semantic discovery 异常不能阻断 Reflection，也不能伪称 semantic-effective。"""
    from llm_loop.methods import reflection as refl

    def boom(_query: str, _limit: int):
        raise RuntimeError("embedding sidecar unavailable")

    client = _CaptureClient()
    outcome = refl.reflect_on_episode(
        llm_client=client,
        store=_ReflectionStore(),  # type: ignore[arg-type]
        episode_entry=_episode(),
        trigger_facts={"run_end_reason": "completed"},
        tool_trace=[],
        run_end_reason="completed",
        final_answer="done",
        method_discovery=boom,
    )

    payload = json.loads(client.calls[0]["messages"][1]["content"])
    assert payload["related_methods"] == []
    assert payload["method_discovery"]["semantic_requested"] is True
    assert payload["method_discovery"]["semantic_effective"] is False
    assert payload["method_discovery"]["semantic_fallback_reason"] == "discovery_error:RuntimeError"
    assert outcome.attempted is True


def test_reflection_method_semantic_off_does_not_invent_diagnostics() -> None:
    """OFF: callback=None 保持旧行为，不声称请求过 semantic。"""
    from llm_loop.methods import reflection as refl

    client = _CaptureClient()
    outcome = refl.reflect_on_episode(
        llm_client=client,
        store=_ReflectionStore(),  # type: ignore[arg-type]
        episode_entry=_episode(),
        trigger_facts={"run_end_reason": "completed"},
        tool_trace=[],
        run_end_reason="completed",
        final_answer="done",
    )

    payload = json.loads(client.calls[0]["messages"][1]["content"])
    assert payload["related_methods"] == []
    assert payload["method_discovery"] == {"semantic_requested": False, "semantic_effective": False}
    assert outcome.method_discovery_diagnostics == payload["method_discovery"]
