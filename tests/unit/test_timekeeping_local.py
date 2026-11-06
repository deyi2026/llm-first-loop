"""Host-local wall-clock contract."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore
from llm_loop.introspection.goal import GoalStore
from llm_loop.runtime.service_control import _local_now
from llm_loop.timekeeping import system_local_now, system_local_now_iso


def _assert_host_local(value: str) -> None:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == datetime.now().astimezone().utcoffset()


def test_system_local_clock_is_aware_and_matches_host_offset() -> None:
    now = system_local_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == datetime.now().astimezone().utcoffset()
    _assert_host_local(system_local_now_iso())


def test_core_persisted_records_use_host_local_offset(tmp_path) -> None:
    sessions = SessionStore(tmp_path / "sessions")
    sid = sessions.create()
    session = sessions.load(sid)
    _assert_host_local(session.created_at)
    _assert_host_local(session.updated_at)

    events = EventStore(tmp_path / "event_logs")
    event = events.append(sid, "test.local_time", {"ok": True})
    _assert_host_local(event.ts)

    goals = GoalStore(tmp_path / "audit")
    goal = goals.create("local time contract")
    _assert_host_local(goal.created_at)
    _assert_host_local(goal.updated_at)


def test_service_control_wall_clock_uses_host_local_offset() -> None:
    _assert_host_local(_local_now())


def _utc_wallclock_offenders(source: str, *, path: str = "<synthetic>") -> list[str]:
    """EVO-20261106-2d7f4703：AST 归一化识别「UTC 墙钟新序列化」调用。

    检测目标（经 import 别名归一化后匹配，前缀/别名拼写不再绕过）：
    - ``<datetime>.datetime.now(<UTC>)`` —— UTC 实参的任何拼写（datetime.UTC、
      datetime.timezone.utc、from-import 别名）；
    - ``<datetime>.datetime.utcnow()`` —— 无时区意识的 UTC 墙钟。
    AST 不可解析 → 返回 ``["<unparseable>"]``，由调用方回退子串扫描。
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ["<unparseable>"]

    # import 别名表：绑定名 → 归一化点路径（import a.b as c → c=a.b；from m import x as y → y=m.x）
    alias: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                alias[name.asname or name.name.split(".")[0]] = name.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for name in node.names:
                alias[name.asname or name.name] = f"{node.module}.{name.name}"

    def dotted(node: ast.AST) -> str:
        parts: list[str] = []
        cur: ast.AST = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(alias.get(cur.id, cur.id))
            return ".".join(reversed(parts))
        return ""

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = dotted(node.func)
        if not callee:
            continue
        if callee.endswith("datetime.utcnow"):
            offenders.append(f"{path}:{node.lineno} {callee}()")
            continue
        if callee.endswith("datetime.now"):
            for arg in node.args:
                argd = dotted(arg)
                if argd.endswith("datetime.UTC") or argd.endswith("timezone.utc"):
                    offenders.append(f"{path}:{node.lineno} {callee}({argd})")
                    break
    return offenders


def test_utc_wallclock_guard_blocks_aliased_spellings() -> None:
    """RULE-AI-35 应拦实测：别名/前缀拼写逐样本仍被拦（2026-11-06 前 7 处绕过史的回归锁）。"""
    should_block = {
        "直接拼写": "import datetime\nx = datetime.datetime.now(datetime.UTC).isoformat()",
        "模块别名": "import datetime as _dt\nx = _dt.datetime.now(_dt.UTC).isoformat()",
        "from-import 别名": "from datetime import datetime as dt, UTC as _UTC\nx = dt.now(_UTC).isoformat()",
        "timezone.utc 拼写": "from datetime import datetime, timezone\nx = datetime.now(timezone.utc).isoformat()",
        "模块别名+timezone": "import datetime as d\nx = d.datetime.now(d.timezone.utc).isoformat()",
        "utcnow": "import datetime\nx = datetime.datetime.utcnow().isoformat()",
        "无序列化也拦": "import datetime as _dt\nt = _dt.datetime.now(_dt.UTC)",
    }
    for label, code in should_block.items():
        assert _utc_wallclock_offenders(code) != [], f"应拦样本未被拦: {label}"

    clean = {
        "授权时钟": "from llm_loop.timekeeping import system_local_now_iso\nx = system_local_now_iso()",
        "本地时区墙钟": "import datetime\nx = datetime.datetime.now().astimezone().isoformat()",
        "fromisoformat 解析": "import datetime\nx = datetime.datetime.fromisoformat(s)",
        "date.today": "import datetime\nx = datetime.date.today().isoformat()",
    }
    for label, code in clean.items():
        assert _utc_wallclock_offenders(code) == [], f"误拦清白样本: {label}"


def test_source_does_not_serialize_new_wall_clock_in_utc() -> None:
    """New LFL-owned wall-clock records must use the host-local authority.

    EVO-20261106-2d7f4703：子串扫描 → AST 归一化扫描；AST 不可解析的文件
    回退子串扫描（保守双模式）。timekeeping.py 为授权实现本体，豁免。
    """
    root = Path(__file__).resolve().parents[2] / "src" / "llm_loop"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        rel = str(path.relative_to(root))
        if rel == "timekeeping.py":
            continue  # 授权时钟源定义处
        text = path.read_text(encoding="utf-8")
        found = _utc_wallclock_offenders(text, path=rel)
        if found == ["<unparseable>"]:
            # 回退子串扫描（EVO 原文口径）
            for pat in ("datetime.now(UTC)", "utcnow()", ".UTC).isoformat"):
                if pat in text:
                    offenders.append(f"{rel} <substring-fallback:{pat}>")
            continue
        offenders.extend(found)
    assert offenders == [], f"UTC 墙钟新序列化（含别名拼写）: {offenders}"


def test_superseded_at_stamps_use_single_host_local_authority() -> None:
    """EVO-20261106-2d7f4703 附带：superseded_at 两侧（engine/factory）统一 host-local 授权。

    历史混用：engine 侧 ``_dt.datetime.now(_dt.UTC)`` vs factory 侧
    ``system_local_now_iso()``。统一后源码级断言两侧引用同一授权函数。
    """
    root = Path(__file__).resolve().parents[2] / "src" / "llm_loop"
    engine = (
        root / "core" / "loop" / "engine_services" / "compaction_gate.py"
    ).read_text(encoding="utf-8")
    factory = (root / "factory.py").read_text(encoding="utf-8")
    assert 'prev["superseded_at"] = system_local_now_iso()' in engine
    assert 'payload["superseded_at"] = system_local_now_iso()' in factory
