"""协调通道程序级注入测试（RULE-AI-14 实现层，2026-08-16）.

验证 engine._interop_inbox_messages:
- pending 消息 → 注入 system 消息（含 id/topic/body/文件路径提示）
- status=done / 格式坏 / 空 body → 跳过
- 目录不存在 → 空列表（fail-open，不抛异常）
- 装配点 _build_llm_messages 首条为 inbox system 消息
"""

import json

import pytest

from llm_loop.core.loop.engine import LoopEngine


def _bare_engine() -> LoopEngine:
    return LoopEngine.__new__(LoopEngine)  # 纯方法测试，绕过 __init__


def test_inject_pending_message(tmp_path, monkeypatch):
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    (inbox / "20260816-005_dsh-test.json").write_text(
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

    msgs = _bare_engine()._interop_inbox_messages()
    assert len(msgs) == 1
    m = msgs[0]
    assert m.role == "system"
    assert "20260816-005" in m.content
    assert "task" in m.content
    assert "请复核风险清单" in m.content
    assert "data/interop/lfl_to_dsh/pending/20260816-005_dsh-test.json" in m.content
    # 不打 injected_system 标记（本地 provider 也须可见）
    assert not (m.metadata or {}).get("injected_system")


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


def test_notify_duplicate_auto_archive(tmp_path, monkeypatch):
    """EVO-20260817-c35c9178: 重复 notify（同 from/ref/body 指纹）→ 不注入 + 自动归档."""
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    _write_msg(inbox, "n1.json", "notify", "job-1 完成", ref="job-1", msg_id="n1")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    eng = _bare_engine()

    # 首见 → 注入回显，文件仍在 pending（AI 按协议处理）
    msgs = eng._interop_inbox_messages()
    assert len(msgs) == 1 and "job-1 完成" in msgs[0].content
    assert (inbox / "n1.json").exists()

    # 同指纹重复（scheduler 重复写同提醒）→ 不注入 + 自动归档（done + 移走）
    _write_msg(inbox, "n1-dup.json", "notify", "job-1 完成", ref="job-1", msg_id="n1-dup")
    msgs2 = eng._interop_inbox_messages()
    assert msgs2 == []
    assert not (inbox / "n1-dup.json").exists()
    done = tmp_path / "interop" / "lfl_to_dsh" / "done" / "n1-dup.json"
    assert done.exists()
    assert json.loads(done.read_text())["status"] == "done"


def test_notify_first_seen_not_archived(tmp_path, monkeypatch):
    """首见 notify 不自动归档（可见性不变，等待 AI 按协议处理）."""
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    _write_msg(inbox, "n2.json", "notify", "job-2 完成", ref="job-2", msg_id="n2")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    msgs = _bare_engine()._interop_inbox_messages()
    assert len(msgs) == 1 and (inbox / "n2.json").exists()


def test_coordinate_not_auto_archived(tmp_path, monkeypatch):
    """coordinate/task 类消息不自动归档（保持原协议，AI 处理）."""
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    _write_msg(inbox, "t1.json", "task", "请复核风险清单", ref="", msg_id="t1")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    eng = _bare_engine()
    for _ in range(2):  # 两次扫描都不自动归档（非 notify）
        msgs = eng._interop_inbox_messages()
        assert len(msgs) == 1 and "请复核风险清单" in msgs[0].content
        assert (inbox / "t1.json").exists()


def test_build_messages_injects_inbox_after_memory(tmp_path, monkeypatch):
    """装配点验证: _build_llm_messages 中 inbox 注入在 memory 之后（每轮必感知）.

    真实机制（P1-FEISHU _append_or_merge）: system 角色消息全部合并追加进
    system_prompt（out[0]），非独立消息——故断言顺序而非独立槽位。
    追加式合并保持 system 原内容前缀稳定（服务端 KV 缓存命中），
    inbox 段重算成本 = 其自身长度（几百字符，一次性）。
    """
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
                "topic": "notify",
                "body": "通道注入装配点验证",
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
    # 注入内容在 user 消息中保留（AI 可见）——且 inbox 在 memory 之后
    # （EVO-20260818 tail 模式: inbox 更靠后——提交尾部追加，前缀 system+memory 稳定）
    users = [m["content"] for m in out if m["role"] == "user"]
    joined = "\n".join(users)
    assert "MEM-1" in joined  # memory 注入生效（转 user 保留）
    assert "20260816-006" in joined  # inbox 注入生效（每轮必感知）
    assert joined.index("20260816-006") > joined.index("MEM-1")  # inbox 在 memory 之后


def test_tail_mode_keeps_base_and_stores_tail(tmp_path, monkeypatch):
    """EVO-20260818（spec §5.3.1-1 c/d，grill-me B1）: tail 模式——base 原样
    （前缀不插注入，system+稳定历史前缀字节不变），注入消息存 _interop_tail_messages
    供 build 末尾追加."""
    from llm_loop.core.message import Message, MessageSource

    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    _write_msg(inbox, "t2.json", "task", "尾部注入验证", msg_id="t2")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    eng = _bare_engine()
    base = [Message(role="user", content="H1", source=MessageSource.USER)]
    out, prefix_len = eng._inject_interop_messages(list(base), 0, "s1")
    assert out == base  # base 原样（前缀不变）
    assert prefix_len == 0
    tail = getattr(eng, "_interop_tail_messages", None)
    assert tail is not None and len(tail) == 1
    assert "尾部注入验证" in tail[0].content


def test_prefix_mode_restores_old_behavior(tmp_path, monkeypatch):
    """INTEROP_INJECT_TAIL=0 → 回退旧行为（注入插 memory 之后、历史之前）."""
    from llm_loop.core.message import Message, MessageSource

    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    _write_msg(inbox, "t3.json", "task", "前缀注入验证", msg_id="t3")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INTEROP_INJECT_TAIL", "0")
    eng = _bare_engine()
    base = [Message(role="user", content="H1", source=MessageSource.USER)]
    out, prefix_len = eng._inject_interop_messages(list(base), 0, "s1")
    assert len(out) == 2 and "前缀注入验证" in out[0].content  # 注入在 base 之前
    assert prefix_len == 1


def test_build_messages_memory_tail_and_gate_note_user(tmp_path, monkeypatch):
    """2026-08-18 注入纪律修复装配验证（spec §5.3.1-1c / §5.3.1-5）:

    - memory 检索注入 → 提交尾部 user 消息（不再前置 system 段——前置随查询变化会断前缀）
    - 门禁干预标记 → 提交尾部 user 消息（非 system，消除守卫规则 B 误报源）
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
    # 漂移检测激活路径由 test_cache_monitor 覆盖；此处直接置位验证装配（build 内消费）
    engine._cache_monitor._gate_note_pending = True
    # memory 注入（检索结果，随查询变化）→ 应尾部追加
    mem = Message(role="system", content="MEM-TAIL: 记忆", source=MessageSource.SYSTEM)
    out = engine._build_llm_messages(engine.session.load(sess), [mem], max_chars=200000)
    roles = [m["role"] for m in out]
    # 纪律: 仅 out[0] 为 system（主体）——无任何非首位 system（守卫规则 B 无触发源）
    assert roles[0] == "system"
    assert all(r != "system" for r in roles[1:])
    # memory 尾部 user 保留（AI 可见），不进 system 主体
    assert "MEM-TAIL" not in out[0]["content"]
    tail_join = "\n".join(m.get("content", "") for m in out[1:])
    assert "MEM-TAIL" in tail_join
    # 门禁干预标记: 尾部 user（非 system），固定文本可辨识
    assert out[-1]["role"] == "user"
    assert GATE_NOTE_CONTENT in out[-1]["content"]
