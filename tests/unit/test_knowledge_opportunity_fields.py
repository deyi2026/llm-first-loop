"""P0b 实施项：机会分母/业务标签的 producer 字段（DESIGN v0.8 预注册配套）.

覆盖：
- knowledge.run_outcome 记录 advisor_mode（该 run 真实执行的 advisor 模式），
  使历史"payload 未统一记录 mode"的审计缺口对新事件关闭；
- run.end 携带 knowledge_run_ref / knowledge_advisor_mode：
  * tracker 存在 → 绑定实际 run_ref（run 级 join 主键）与实际 mode；
  * tracker 不存在 → 回退已解析配置 mode，使"advisor 已启用但该 run 未产生
    任何 knowledge 事件"的机会分母行可构造（此前无痕迹即不可测）；
  * 配置不可得 → None（unknown，不猜）。
诚实边界：这些是 producer 观测字段，不构成任务成功/收益标签；旧事件不回填。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from llm_loop.core.loop.engine_services.knowledge_runtime import KnowledgeRun
from llm_loop.introspection.knowledge_advisor import KnowledgeAdvisor


def _search(*, kind: str, **_unused: Any):
    return {
        "method": [], "experience": [], "lesson": [],
    }[kind]


def _run(mode: str = "shadow") -> tuple[KnowledgeRun, list]:
    events: list = []
    run = KnowledgeRun(
        advisor=KnowledgeAdvisor(_search, mode=mode),
        session_id="web-one", run_ref="web-one:turn:1:run:g1",
        event_append=lambda sid, typ, payload: events.append((sid, typ, payload)),
        canary_sessions=frozenset({"web-one"}),
    )
    return run, events


def test_run_outcome_records_advisor_mode() -> None:
    run, events = _run(mode="shadow")
    run.finish(
        trace=[], tool_messages=[], reason="completed", rounds=1,
        tokens_in=10, tokens_out=5, duration_ms=7, model_used="m",
        run_incomplete=False,
    )
    kinds = [e[1] for e in events]
    assert kinds[-1] == "knowledge.run_outcome"
    assert events[-1][2]["advisor_mode"] == "shadow"
    # 既有语义不回归：task_benefit 仍如实 not_evaluated，不得借 mode 字段推导收益。
    assert events[-1][2]["task_benefit"] == "not_evaluated"


def test_run_end_fields_bind_actual_tracker() -> None:
    from llm_loop.core.loop.engine_services.run_finalizer import (
        _knowledge_terminal_fields,
    )

    tracker = SimpleNamespace(
        run_ref="web-one:turn:1:run:g1", advisor=SimpleNamespace(mode="shadow"),
    )
    host = SimpleNamespace(settings=None)
    assert _knowledge_terminal_fields(host, tracker) == {
        "knowledge_run_ref": "web-one:turn:1:run:g1",
        "knowledge_advisor_mode": "shadow",
    }


def test_run_end_fields_tracker_without_mode_still_binds_run_ref() -> None:
    from llm_loop.core.loop.engine_services.run_finalizer import (
        _knowledge_terminal_fields,
    )

    tracker = SimpleNamespace(run_ref="web-one:turn:2:run:g2", advisor=None)
    assert _knowledge_terminal_fields(SimpleNamespace(settings=None), tracker) == {
        "knowledge_run_ref": "web-one:turn:2:run:g2",
        "knowledge_advisor_mode": None,
    }


def test_run_end_fields_absent_tracker_falls_back_to_config_mode() -> None:
    from llm_loop.core.loop.engine_services.run_finalizer import (
        _knowledge_terminal_fields,
    )

    host = SimpleNamespace(
        settings=SimpleNamespace(
            tool_runtime=SimpleNamespace(knowledge_advisor_mode="shadow"),
        ),
    )
    assert _knowledge_terminal_fields(host, None) == {
        "knowledge_run_ref": None,
        "knowledge_advisor_mode": "shadow",
    }


def test_run_end_fields_unknown_when_config_unavailable() -> None:
    from llm_loop.core.loop.engine_services.run_finalizer import (
        _knowledge_terminal_fields,
    )

    assert _knowledge_terminal_fields(SimpleNamespace(settings=None), None) == {
        "knowledge_run_ref": None,
        "knowledge_advisor_mode": None,
    }
