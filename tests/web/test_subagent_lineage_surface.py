"""Web subagent lineage surface（对齐 DSH Subagent Header Lineage）: 机械拓扑事实.

契约（feature/webui-subagent-lineage-20260922）：
- /api/v1/agents/tree 在既有静态层级（id/parent_id/is_subagent）之上，为子代理节点
  附着 runner 的机械活动事实（activity running/inactive、outcome、settlement）；
  runner 缺失或 topology 未知时**不伪造**——字段缺省，不默认 inactive。
- 事实只来自 SubAgentRunner.topology_snapshot（local_active/terminal/outcome/
  settlement_state），Web 层不做任何语义派生。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from llm_loop.web import build_app


class _StubRunner:
    """最小 stub：只提供 topology_snapshot 机械事实，验证 Web 投影不越权."""

    def __init__(self, facts: dict[str, dict[str, object]]) -> None:
        self._facts = facts

    def topology_snapshot(self, child_session_id: str) -> dict[str, object] | None:
        return self._facts.get(child_session_id)


def _client(engine) -> TestClient:
    return TestClient(build_app(engine=engine))


def _nodes(engine, sid: str):
    resp = _client(engine).get("/api/v1/agents/tree")
    assert resp.status_code == 200
    return {n["id"]: n for n in resp.json()["nodes"] if n["id"] == sid}


def test_tree_enriches_subagent_activity_from_runner(build_test_engine) -> None:
    engine, _ = build_test_engine([])
    parent = engine.session.create()
    child = engine.session.create()

    engine.subagent_runner = _StubRunner(
        {
            child: {
                "child_id": child,
                "parent_id": parent,
                "owner_state": "local_active",
                "local_active": True,
                "terminal": False,
                "outcome": "",
                "settlement_state": "uncollected",
            }
        }
    )
    node = _nodes(engine, child)[child]
    assert node["activity"] == "running"
    assert node["outcome"] == ""
    assert node["settlement"] == "uncollected"


def test_tree_marks_terminal_child_with_outcome(build_test_engine) -> None:
    engine, _ = build_test_engine([])
    parent = engine.session.create()
    child = engine.session.create()

    engine.subagent_runner = _StubRunner(
        {
            child: {
                "child_id": child,
                "parent_id": parent,
                "owner_state": "terminal_local",
                "local_active": False,
                "terminal": True,
                "outcome": "completed",
                "settlement_state": "collected",
            }
        }
    )
    node = _nodes(engine, child)[child]
    assert node["activity"] == "inactive"
    assert node["outcome"] == "completed"
    assert node["settlement"] == "collected"


def test_tree_never_fabricates_activity(build_test_engine) -> None:
    engine, _ = build_test_engine([])
    parent = engine.session.create()
    plain = engine.session.create()

    # runner 存在但对未知 child 返回 None → 不伪造 activity
    engine.subagent_runner = _StubRunner({})
    node = _nodes(engine, plain)[plain]
    assert "activity" not in node
    assert "outcome" not in node
    assert "settlement" not in node

    # runner 完全缺失（精简装配）→ 同样不伪造
    engine.subagent_runner = None
    node = _nodes(engine, plain)[plain]
    assert "activity" not in node
