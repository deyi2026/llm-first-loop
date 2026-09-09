"""Rule-first operator review helper tests.

Ordinary model runs no longer scan periodic self-eval/executing/proc-stale state.
This file covers the explicit human pending-review control surface and ghost defense.
"""

from __future__ import annotations

from llm_loop.introspection.loop_signals import LoopSignalDetector


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


# ── M49 RULE-AI-00: 默认不弹窗（web/feishu/测试无人值守路径仅文本注入）──
class _PendingStore:
    _path: None = None

    def __init__(self, items) -> None:
        self._items = items
        self.reviewed: list = []
        self._path = None

    def list(self, status=""):
        if status:
            return [i for i in self._items if i.get("status") == status]
        return self._items

    def review(self, sid, decision):
        self.reviewed.append((sid, decision))
        return {"id": sid, "status": decision}


def test_pending_review_no_popup_default(tmp_path, monkeypatch):
    """默认构造 + pending_review → 零扫描权威：不 confirm、不生成事件."""
    store = _PendingStore([{"id": "EVO-NOPOP-1", "status": "pending_review", "content": "x"}])
    detector = LoopSignalDetector()
    calls: list = []
    monkeypatch.setattr(
        "llm_loop.introspection.loop_signals.confirm",
        lambda *a, **k: calls.append("confirm") or True,
    )
    ev = detector.check_pending_review(store)
    assert calls == []  # 默认不弹窗
    assert ev is None


def test_pending_review_no_popup_no_auto_review(tmp_path, monkeypatch):
    """非弹窗模式: store.review 未被调用、忽略清单不落盘、_prompted_ids 不更新."""
    store = _PendingStore([{"id": "EVO-NOPOP-2", "status": "pending_review", "content": "x"}])
    detector = LoopSignalDetector()
    monkeypatch.setattr("llm_loop.introspection.loop_signals.confirm", lambda *a, **k: True)
    ev = detector.check_pending_review(store)
    assert ev is None
    assert store.reviewed == []  # 不自动审阅
    assert not (tmp_path / "audit" / "pending_ignored.jsonl").exists()  # 不写忽略清单
    assert detector._prompted_ids == set()  # 不更新已提示列表


def test_pending_review_popup_enabled_keeps_behavior(tmp_path, monkeypatch):
    """popup_pending_review=True → 保留既有弹窗行为（确认→accepted；拒绝→文本引导）."""
    confirmed_store = _PendingStore(
        [{"id": "EVO-POPUP-1", "status": "pending_review", "content": "x"}]
    )
    detector = LoopSignalDetector(popup_pending_review=True)
    monkeypatch.setattr("llm_loop.introspection.loop_signals.confirm", lambda *a, **k: True)
    ev = detector.check_pending_review(confirmed_store)
    assert confirmed_store.reviewed == [("EVO-POPUP-1", "accepted")]  # 确认自动审阅
    assert ev is not None and "accepted" in ev.fact

    rejected_store = _PendingStore(
        [{"id": "EVO-POPUP-2", "status": "pending_review", "content": "x"}]
    )
    detector2 = LoopSignalDetector(popup_pending_review=True)
    monkeypatch.setattr("llm_loop.introspection.loop_signals.confirm", lambda *a, **k: False)
    ev2 = detector2.check_pending_review(rejected_store)
    assert rejected_store.reviewed == []  # 拒绝不自动审阅
    assert ev2 is not None and "待审阅" in ev2.fact


def test_pending_review_no_popup_store_fail_open(tmp_path, monkeypatch):
    """非弹窗模式 store.list 抛 OSError → None（fail-open，DFX-REL-08）."""
    from pathlib import Path

    real_open = Path.open

    def _broken(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", _broken)
    try:
        detector = LoopSignalDetector()
        assert detector.check_pending_review(_PendingStore([])) is None
    finally:
        monkeypatch.setattr(Path, "open", real_open)


# ── EVO-20260811-f94e5306 补丁: 幽灵建议防御 ──
def test_pending_review_ghost_ignored(tmp_path, monkeypatch):

    from llm_loop.introspection.loop_signals import LoopSignalDetector

    detector = LoopSignalDetector(popup_pending_review=True)
    detector._prompted_ids = set()

    class _GhostStore:
        _path = tmp_path / "audit" / "evolution_suggestions.jsonl"

        def list(self, status=None):
            return [{"id": "EVO-GHOST-1", "content": "幽灵建议内容"}]

        def review(self, sid, decision):
            return None  # 建议不存在（幽灵）

    monkeypatch.setattr("llm_loop.introspection.loop_signals.confirm", lambda *a, **k: True)
    ev = detector.check_pending_review(_GhostStore())
    assert ev is not None and "已加入忽略清单" in ev.fact
    # 已忽略 → 下次不弹
    assert detector.check_pending_review(_GhostStore()) is None
    # 忽略清单落盘
    assert (tmp_path / "audit" / "pending_ignored.jsonl").exists()
    assert "EVO-GHOST-1" in (tmp_path / "audit" / "pending_ignored.jsonl").read_text(
        encoding="utf-8"
    )


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

    from llm_loop.introspection.loop_signals import LoopSignalDetector

    detector = LoopSignalDetector(popup_pending_review=True)
    detector._prompted_ids = set()

    class _NormalStore:
        _path = tmp_path / "audit" / "evolution_suggestions.jsonl"

        def list(self, status=None):
            return [{"id": "EVO-NORMAL-1", "content": "正常建议"}]

        def review(self, sid, decision):
            return {"id": sid, "status": "accepted"}

    monkeypatch.setattr("llm_loop.introspection.loop_signals.confirm", lambda *a, **k: True)
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
        _json.dumps({"sid": "EVO-GHOST-OLD", "content": "启用语义检索能力以提升长期记忆"}) + "\n",
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
