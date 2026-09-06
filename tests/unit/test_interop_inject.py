"""协调通道程序级注入测试（RULE-AI-14 实现层，2026-08-16）.

验证 engine._interop_inbox_messages:
- notify/backlog → observability/UI only，零 prompt Message
- coordinate/task pending → E26 保持 pending 等用户输入侧授权，零 prompt/零自动消费
- status=done / 格式坏 / 空 body → 跳过
- 目录不存在 → 空列表（fail-open，不抛异常）
- build/provider wire 不包含任何未授权 interop 正文
"""

import json

import pytest

from llm_loop.core.loop.engine import LoopEngine


def _bare_engine() -> LoopEngine:
    return LoopEngine.__new__(LoopEngine)  # 纯方法测试，绕过 __init__


def test_task_pending_waits_for_user_authorization(tmp_path, monkeypatch):
    """E26: task/coordinate 只保留 pending/UI，不能自动变成模型输入或被消费."""
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    path = inbox / "20260816-005_dsh-test.json"
    path.write_text(
        json.dumps(
            {
                "id": "20260816-005",
                "from": "dsh",
                "to": "lfl",
                "ts": "2026-08-16T20:00:00",
                "topic": "task",
                "ref": "",
                "body": "请复核风险清单",
                "status": "pending",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    eng = _bare_engine()
    actions: list[tuple[str, str, str]] = []
    eng._record_action = lambda kind, status, detail: actions.append((kind, status, detail))

    assert eng._interop_inbox_messages() == []
    assert path.exists(), "未授权 external task 必须保留 pending，等待用户处理"
    assert actions == [(
        "interop.external_input",
        "awaiting_user_authorization",
        "id=20260816-005;topic=task;from=dsh;ref=;prompt_chars=0",
    )]
    # 同进程再次扫描不重复刷 action。
    assert eng._interop_inbox_messages() == []
    assert len(actions) == 1


def test_skip_done_and_bad_files(tmp_path, monkeypatch):
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    (inbox / "a.json").write_text(
        json.dumps(
            {
                "id": "a",
                "status": "done",
                "body": "已处理",
            }
        ),
        encoding="utf-8",
    )  # done → 跳过
    (inbox / "b.json").write_text("not json{", encoding="utf-8")  # 格式坏 → 跳过
    (inbox / "c.json").write_text(
        json.dumps(
            {
                "id": "c",
                "status": "pending",
                "body": "  ",
            }
        ),
        encoding="utf-8",
    )  # 空 body → 跳过
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))

    assert _bare_engine()._interop_inbox_messages() == []
    # EVO-20260825 任务9（§5.4.1-5）: 解析失败文件应隔离到 dead/（不静默滞留）
    dead = inbox / "dead" / "b.json"
    assert dead.exists(), "格式坏文件应隔离到 pending/dead/"
    assert not (inbox / "b.json").exists()


def test_missing_dir_fail_open(tmp_path, monkeypatch):
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path / "nope"))
    assert _bare_engine()._interop_inbox_messages() == []  # 不抛异常


def _write_msg(inbox, name, topic, body, ref="", msg_id=None):
    (inbox / name).write_text(
        json.dumps(
            {
                "id": msg_id or name,
                "from": "dsh",
                "to": "lfl",
                "ts": "2026-08-17T12:00:00",
                "topic": topic,
                "ref": ref,
                "body": body,
                "status": "pending",
            }
        ),
        encoding="utf-8",
    )


def test_notify_first_and_duplicate_are_observability_only(tmp_path, monkeypatch):
    """R8.12/E25: 首见/重复 notify 均归档到 done，零 prompt Message."""
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    _write_msg(inbox, "n1.json", "notify", "job-1 完成", ref="job-1", msg_id="n1")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    eng = _bare_engine()

    # 首见 → 不构造模型消息，直接转 done/ 供 UI/retrieval。
    msgs = eng._interop_inbox_messages()
    assert msgs == []
    assert not (inbox / "n1.json").exists()
    done1 = tmp_path / "interop" / "lfl_to_dsh" / "done" / "n1.json"
    assert done1.exists()
    first = json.loads(done1.read_text())
    assert first["status"] == "done" and first["body"] == "job-1 完成"

    # 同指纹重复（scheduler 重复写同提醒）→ 同样只归档，不重新获得 prompt authority。
    _write_msg(inbox, "n1-dup.json", "notify", "job-1 完成", ref="job-1", msg_id="n1-dup")
    msgs2 = eng._interop_inbox_messages()
    assert msgs2 == []
    assert not (inbox / "n1-dup.json").exists()
    done = tmp_path / "interop" / "lfl_to_dsh" / "done" / "n1-dup.json"
    assert done.exists()
    assert json.loads(done.read_text())["status"] == "done"


def test_notify_action_trace_has_zero_prompt_chars(tmp_path, monkeypatch):
    """notify 的结构化 observability 保留，但内容不进入模型."""
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    _write_msg(inbox, "n2.json", "notify", "job-2 完成", ref="job-2", msg_id="n2")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    eng = _bare_engine()
    actions: list[tuple[str, str, str]] = []
    eng._record_action = lambda kind, status, detail: actions.append((kind, status, detail))

    assert eng._interop_inbox_messages() == []
    assert actions == [("interop.notify", "observed_only", "id=n2;from=dsh;ref=job-2;prompt_chars=0")]


def test_backlog_count_is_observability_only(tmp_path, monkeypatch):
    """E25/E26: 堆积只记 action；9 条 task 全保留 pending，不自动消费/注入."""
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    for i in range(9):
        _write_msg(inbox, f"t{i}.json", "task", f"task-{i}", msg_id=f"t{i}")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    eng = _bare_engine()
    actions: list[tuple[str, str, str]] = []
    eng._record_action = lambda kind, status, detail: actions.append((kind, status, detail))

    assert eng._interop_inbox_messages() == []
    assert all((inbox / f"t{i}.json").exists() for i in range(9))
    assert (
        "interop.pending_backlog",
        "observed_only",
        "pending=9;scan_limit=8;prompt_chars=0",
    ) in actions


def test_build_provider_wire_excludes_notify_but_keeps_done_record(
    build_test_engine, tmp_path, monkeypatch
):
    """E25 end-to-end: pending notify is consumed to done/UI and never appears in provider wire."""
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    _write_msg(
        inbox,
        "n-wire.json",
        "notify",
        "job-sensitive-result-complete",
        ref="job-wire",
        msg_id="notify-wire-id",
    )
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    engine, _fake = build_test_engine([])
    sid = engine.session.create()

    out = engine._build_llm_messages(engine.session.load(sid), [], max_chars=200_000)
    wire = json.dumps(out, ensure_ascii=False)
    assert "notify-wire-id" not in wire
    assert "job-sensitive-result-complete" not in wire
    done = tmp_path / "interop" / "lfl_to_dsh" / "done" / "n-wire.json"
    payload = json.loads(done.read_text(encoding="utf-8"))
    assert payload["status"] == "done"
    assert payload["body"] == "job-sensitive-result-complete"


def test_coordinate_stays_pending_and_never_auto_injects(tmp_path, monkeypatch):
    """E26: coordinate is not auto-consumed or auto-injected without user authorization."""
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    _write_msg(inbox, "t1.json", "coordinate", "请复核风险清单", ref="coord-1", msg_id="t1")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    eng = _bare_engine()

    assert eng._interop_inbox_messages() == []
    assert (inbox / "t1.json").exists()
    assert eng._interop_inbox_messages() == []
    assert (inbox / "t1.json").exists()


def test_build_messages_excludes_unapproved_interop(tmp_path, monkeypatch):
    """E26 end-to-end: memory 可见，但未授权 task 正文不得进入 provider wire."""
    from llm_loop.config import Settings
    from llm_loop.core.message import Message, MessageSource
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.tools.registry import ToolRegistry

    class _Fake:
        def chat(self, messages, tools, **kw):
            return LLMResponse(content="ok", tool_calls=[], provider="fake")

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()
                return LLMResponse(content="ok", tool_calls=[], provider="fake")

            return _gen()

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    engine = LoopEngine(
        llm_client=_Fake(),
        registry=ToolRegistry(),
        memory=None,
        session=SessionStore(tmp_path / "sessions"),
        settings=settings,
    )
    # 装配点真实路径: 写 inbox 文件 → 不 monkeypatch 方法，走真实扫描
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    (inbox / "20260816-006_dsh-x.json").write_text(
        json.dumps(
            {
                "id": "20260816-006",
                "from": "dsh",
                "to": "lfl",
                "topic": "task",
                "body": "通道任务装配点验证",
                "status": "pending",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))

    sess = engine.session.create("interop-test") if hasattr(engine.session, "create") else None
    if sess is None:
        pytest.skip("SessionStore 无 create 接口")
    # memory 注入非空时，inbox 必须在 memory 之后（合并进 system 前缀, 追加式保持前缀稳定）
    mem = Message(role="system", content="MEM-1: 记忆片段", source=MessageSource.SYSTEM)
    out = engine._build_llm_messages(engine.session.load(sess), [mem], max_chars=200000)
    # 2026-08-18 对齐 DSH: system 主体静态——注入（memory/inbox）转独立 user 消息
    assert out[0]["role"] == "system"  # 主体
    content = out[0]["content"]
    assert "MEM-1" not in content and "20260816-006" not in content  # 注入不进主体
    users = [m["content"] for m in out if m["role"] == "user"]
    joined = "\n".join(users)
    assert "MEM-1" not in joined  # memory 参数已退为 compatibility/retrieval-only
    assert "20260816-006" not in joined
    assert "通道任务装配点验证" not in joined
    assert (inbox / "20260816-006_dsh-x.json").exists(), "未授权 task 应保留 pending"


def test_tail_mode_does_not_store_unapproved_interop_tail(tmp_path, monkeypatch):
    """E26: legacy tail mode cannot turn pending external task into an in-memory prompt slot."""
    from llm_loop.core.message import Message, MessageSource

    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    _write_msg(inbox, "t2.json", "task", "尾部注入验证", msg_id="t2")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    eng = _bare_engine()
    base = [Message(role="user", content="H1", source=MessageSource.USER)]
    out, prefix_len = eng._inject_interop_messages(list(base), 0, "s1")
    assert out == base
    assert prefix_len == 0
    assert getattr(eng, "_interop_tail_messages", None) in (None, [])
    assert (inbox / "t2.json").exists()


def test_interop_observability_has_no_err1210_defer_state():
    """P2-B: interop scanning is prompt-neutral and independent of ERR1210 recovery state."""
    import inspect

    from llm_loop.core.loop.engine_services.interop import InteropService

    src = inspect.getsource(InteropService._inject_interop_messages)
    assert "deferred_replay" not in src
    assert "SlotKind" not in src


def test_prefix_mode_cannot_restore_external_auto_injection(tmp_path, monkeypatch):
    """E26: INTEROP_INJECT_TAIL=0 no longer restores the retired automatic prompt path."""
    from llm_loop.core.message import Message, MessageSource

    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    _write_msg(inbox, "t3.json", "task", "前缀注入验证", msg_id="t3")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INTEROP_INJECT_TAIL", "0")
    eng = _bare_engine()
    base = [Message(role="user", content="H1", source=MessageSource.USER)]
    out, prefix_len = eng._inject_interop_messages(list(base), 0, "s1")
    assert out == base
    assert prefix_len == 0
    assert (inbox / "t3.json").exists()


def test_build_messages_memory_tail_and_gate_note_observability_only(tmp_path, monkeypatch):
    """2026-08-18 注入纪律修复装配验证（spec §5.3.1-1c / §5.3.1-5）:

    - memory 检索注入 → 提交尾部 user 消息（不再前置 system 段——前置随查询变化会断前缀）
    - 门禁干预标记 → 仅 runtime observability，零 provider prompt 字符
    - 提交视图仅 system 主体一个 system 角色
    """
    from llm_loop.config import Settings
    from llm_loop.core.cache_health import GATE_NOTE_CONTENT
    from llm_loop.core.message import Message, MessageSource
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.tools.registry import ToolRegistry

    class _Fake:
        def chat(self, messages, tools, **kw):
            return LLMResponse(content="ok", tool_calls=[], provider="fake")

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()
                return LLMResponse(content="ok", tool_calls=[], provider="fake")

            return _gen()

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    engine = LoopEngine(
        llm_client=_Fake(),
        registry=ToolRegistry(),
        memory=None,
        session=SessionStore(tmp_path / "sessions"),
        settings=settings,
    )
    sess = engine.session.create("gate-build-test") if hasattr(engine.session, "create") else None
    if sess is None:
        pytest.skip("SessionStore 无 create 接口")
    # 激活门禁干预: 修复后稳定段 = system+固定注入（恒定指纹），preflight 永不漂移——
    # 漂移检测激活路径由 test_cache_monitor 覆盖；此处直接置位验证装配（build 内消费）。
    # EVO-20260825 任务1（§5.3）: per-session 分桶后 gate_note_pending 走 bucket。
    loaded = engine.session.load(sess)
    engine._cache_monitor._get_bucket(loaded.session_id).gate_note_pending = True
    # memory 注入（检索结果，随查询变化）→ 应尾部追加
    mem = Message(role="system", content="MEM-TAIL: 记忆", source=MessageSource.SYSTEM)
    out = engine._build_llm_messages(loaded, [mem], max_chars=200000)
    roles = [m["role"] for m in out]
    # 纪律: 仅 out[0] 为 system（主体）——无任何非首位 system（守卫规则 B 无触发源）
    assert roles[0] == "system"
    assert all(r != "system" for r in roles[1:])
    # memory 参数只保 compatibility 形状；自动 prompt 权限已退出。
    assert "MEM-TAIL" not in out[0]["content"]
    tail_join = "\n".join(m.get("content", "") for m in out[1:])
    assert "MEM-TAIL" not in tail_join
    # 门禁干预标记只被消费/观测，不进入 provider prompt。
    assert GATE_NOTE_CONTENT not in tail_join
    assert engine._cache_monitor.take_gate_note(loaded.session_id) is False
