"""单元测试: LoopSignalDetector 二合一（M17 FR-REVIEW-AI-02/03 + M18 AA1 收敛 / design §8.2/8.3）.

覆盖: check_evolution_executing 四态（无 executing → None / 有 → 事件含 id + evolution_complete 引导 /
store=None → None / store.list 抛 OSError → None fail-open）；check_eval_trigger 语义等价
（rounds % interval / milestone）。
"""

from __future__ import annotations

from llm_loop.core.message import Message, MessageSource
from llm_loop.introspection.events import ArchitectureEvent, ArchitectureEventType
from llm_loop.introspection.evolution import EvolutionStore
from llm_loop.introspection.loop_signals import LoopSignalDetector


def _sess():
    class _S:
        def __init__(self) -> None:
            self.messages = [Message(role="user", content="hi", source=MessageSource.USER)]

    return _S()


class _FakeSettings:
    self_eval_remind_enabled = True


class _FakeEvalTrigger:
    def __init__(self, hit) -> None:
        self._hit = hit

    def check(self, *, rounds, task_completed):
        from llm_loop.introspection.evaluator import EvalTrigger

        if self._hit:
            return EvalTrigger(
                trigger="milestone" if task_completed else "periodic",
                fact=f"rounds={rounds}",
                reason="mock",
                suggestion="可调用 self_evaluate",
            )
        return None


class _FakeStatus:
    enabled = True

    def snapshot(self):
        return {"exception_log": []}


def test_executing_none_when_empty(tmp_path):
    """无 executing 演进 → None（不注入）."""
    store = EvolutionStore(tmp_path / "audit")
    d = LoopSignalDetector()
    assert d.check_evolution_executing(store) is None


def test_executing_event_with_id(tmp_path):
    """有 executing 演进 → 事件含 id + evolution_complete 引导."""
    store = EvolutionStore(tmp_path / "audit")
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    store.review(sug.id, "accepted")
    store.transition(sug.id, status="executing")
    d = LoopSignalDetector()
    ev = d.check_evolution_executing(store)
    assert ev is not None
    assert isinstance(ev, ArchitectureEvent)
    assert ev.event_type == ArchitectureEventType.DEVIATION
    assert sug.id in ev.fact
    assert "evolution_complete" in ev.suggestion


def test_executing_none_when_store_none():
    """store=None → None（未装配不检测）."""
    d = LoopSignalDetector()
    assert d.check_evolution_executing(None) is None


def test_executing_check_store_fail_open(tmp_path, monkeypatch):
    """store.list 抛 OSError → None（fail-open 不注入不阻断，DFX-REL-08）."""
    from pathlib import Path

    store = EvolutionStore(tmp_path / "audit")
    real_open = Path.open

    def _broken(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", _broken)
    try:
        d = LoopSignalDetector()
        assert d.check_evolution_executing(store) is None
    finally:
        monkeypatch.setattr(Path, "open", real_open)


def test_eval_trigger_periodic_semantics():
    """check_eval_trigger: periodic（rounds % interval）语义与 T65 一致."""
    d = LoopSignalDetector(
        eval_trigger_detector=_FakeEvalTrigger(hit=True),
        status=_FakeStatus(),
        settings=_FakeSettings(),
    )
    ev = d.check_eval_trigger(_sess(), rounds=50)
    assert ev is not None
    assert ev.event_type == ArchitectureEventType.DEGRADATION
    assert "self_evaluate" in ev.suggestion


def test_eval_trigger_milestone_semantics():
    """check_eval_trigger: milestone（task_completed）语义与 T65 一致."""
    d = LoopSignalDetector(
        eval_trigger_detector=_FakeEvalTrigger(hit=True),
        status=_FakeStatus(),
        settings=_FakeSettings(),
    )
    ev = d.check_eval_trigger(_sess(), rounds=3, milestone=True)
    assert ev is not None
    assert "milestone" in ev.reason or ev.fact == "rounds=3"


def test_eval_trigger_remind_disabled():
    """self_eval_remind_enabled=False → None（不注入）."""

    class _Disabled:
        self_eval_remind_enabled = False

    d = LoopSignalDetector(
        eval_trigger_detector=_FakeEvalTrigger(hit=True),
        status=_FakeStatus(),
        settings=_Disabled(),
    )
    assert d.check_eval_trigger(_sess(), rounds=50) is None


def test_param_signal_removal_grep():
    """M18 AA1 移除面 grep 断言: ParamSignal/check_param_signal/param_signal_enabled 生产逻辑 0 命中（src）."""
    import subprocess
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src"
    r = subprocess.run(
        [
            "grep",
            "-rn",
            "--exclude-dir=__pycache__",
            "ParamSignal\\|check_param_signal\\|param_signal_enabled",
            str(src),
        ],
        capture_output=True,
        text=True,
    )
    # 豁免: 注释/docstring 中的移除登记说明（M18 审计登记行）+ status.build_report_message（不同方法）
    hits = []
    for ln in r.stdout.splitlines():
        stripped = ln.split(":", 2)[-1].strip()
        if "#" in stripped or '"' in stripped or "'''" in stripped or "M18" in ln:
            continue  # 注释/docstring/审计登记
        hits.append(ln)
    assert hits == [], f"移除面残留（生产逻辑）: {hits}"


# ── EVO-20260811-f94e5306 补丁: 幽灵建议防御 ──
def test_pending_review_ghost_ignored(tmp_path, monkeypatch):
    """幽灵建议（确认后 review 返回 None）→ 持久化忽略，下次不再弹."""
    import json as _json

    from llm_loop.introspection.loop_signals import LoopSignalDetector

    detector = LoopSignalDetector()
    detector._prompted_ids = set()

    class _GhostStore:
        _path = tmp_path / "audit" / "evolution_suggestions.jsonl"

        def list(self, status=None):
            return [{"id": "EVO-GHOST-1", "content": "幽灵建议内容"}]

        def review(self, sid, decision):
            return None  # 建议不存在（幽灵）

    monkeypatch.setattr(
        "llm_loop.introspection.loop_signals.confirm", lambda *a, **k: True
    )
    ev = detector.check_pending_review(_GhostStore())
    assert ev is not None and "已加入忽略清单" in ev.fact
    # 已忽略 → 下次不弹
    assert detector.check_pending_review(_GhostStore()) is None
    # 忽略清单落盘
    assert (tmp_path / "audit" / "pending_ignored.jsonl").exists()
    assert "EVO-GHOST-1" in (tmp_path / "audit" / "pending_ignored.jsonl").read_text(encoding="utf-8")


def test_pending_review_ignored_skips_before_confirm(tmp_path, monkeypatch):
    """已忽略的 sid 弹窗前直接跳过（不弹窗、不审阅）."""
    import json as _json

    from llm_loop.introspection.loop_signals import LoopSignalDetector

    detector = LoopSignalDetector()
    detector._prompted_ids = set()
    # 预写忽略清单
    p = tmp_path / "audit" / "pending_ignored.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps({"sid": "EVO-GHOST-2"}) + "\n", encoding="utf-8")

    called: list = []

    class _GhostStore2:
        _path = tmp_path / "audit" / "evolution_suggestions.jsonl"

        def list(self, status=None):
            return [{"id": "EVO-GHOST-2", "content": "x"}]

        def review(self, sid, decision):
            called.append(sid)
            return None

    monkeypatch.setattr(
        "llm_loop.introspection.loop_signals.confirm",
        lambda *a, **k: called.append("confirm") or True,
    )
    assert detector.check_pending_review(_GhostStore2()) is None  # 已忽略 → 不弹
    assert called == []  # confirm 与 review 均未被调用


def test_pending_review_normal_not_ignored(tmp_path, monkeypatch):
    """正常建议（review 返回 dict）→ 正常 accepted 事件，不写忽略清单."""
    import json as _json

    from llm_loop.introspection.loop_signals import LoopSignalDetector

    detector = LoopSignalDetector()
    detector._prompted_ids = set()

    class _NormalStore:
        _path = tmp_path / "audit" / "evolution_suggestions.jsonl"

        def list(self, status=None):
            return [{"id": "EVO-NORMAL-1", "content": "正常建议"}]

        def review(self, sid, decision):
            return {"id": sid, "status": "accepted"}

    monkeypatch.setattr(
        "llm_loop.introspection.loop_signals.confirm", lambda *a, **k: True
    )
    ev = detector.check_pending_review(_NormalStore())
    assert ev is not None and "accepted" in ev.fact
    # 不写忽略清单（正常建议）
    assert not (tmp_path / "audit" / "pending_ignored.jsonl").exists()


def test_pending_review_content_fingerprint_ignored(tmp_path, monkeypatch):
    """同内容不同 ID 的幽灵建议：按内容指纹忽略（防并行会话换 ID 重复弹）."""
    import json as _json

    from llm_loop.introspection.loop_signals import LoopSignalDetector

    # 预写忽略清单（含旧 ID + 内容指纹"启用语义检索"）
    p = tmp_path / "audit" / "pending_ignored.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        _json.dumps({"sid": "EVO-GHOST-OLD", "content": "启用语义检索能力以提升长期记忆"})
        + "\n",
        encoding="utf-8",
    )

    detector = LoopSignalDetector()
    detector._prompted_ids = set()
    called: list = []

    class _GhostStore3:
        _path = tmp_path / "audit" / "evolution_suggestions.jsonl"

        def list(self, status=None):
            return [
                {
                    "id": "EVO-NEW-ID-不同",
                    "content": "启用语义检索能力以提升长期记忆与压缩档案的召回质量：当前架构配置 embedding_provider=none",
                }
            ]

        def review(self, sid, decision):
            called.append(sid)
            return None

    monkeypatch.setattr(
        "llm_loop.introspection.loop_signals.confirm",
        lambda *a, **k: called.append("confirm") or True,
    )
    assert detector.check_pending_review(_GhostStore3()) is None  # 内容指纹命中 → 不弹
    assert called == []  # confirm 与 review 均未调用（新 ID 也被内容指纹拦住）
