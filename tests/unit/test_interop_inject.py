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
    (inbox / "20260816-005_dsh-test.json").write_text(json.dumps({
        "id": "20260816-005", "from": "dsh", "to": "lfl",
        "ts": "2026-08-16T20:00:00", "topic": "task", "ref": "",
        "body": "请复核风险清单", "status": "pending",
    }), encoding="utf-8")
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
    (inbox / "a.json").write_text(json.dumps({
        "id": "a", "status": "done", "body": "已处理",
    }), encoding="utf-8")   # done → 跳过
    (inbox / "b.json").write_text("not json{", encoding="utf-8")  # 格式坏 → 跳过
    (inbox / "c.json").write_text(json.dumps({
        "id": "c", "status": "pending", "body": "  ",
    }), encoding="utf-8")   # 空 body → 跳过
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))

    assert _bare_engine()._interop_inbox_messages() == []


def test_missing_dir_fail_open(tmp_path, monkeypatch):
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path / "nope"))
    assert _bare_engine()._interop_inbox_messages() == []  # 不抛异常


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
        llm_api_key="k", llm_base_url="https://x/v1", llm_model="m",
        data_dir=str(tmp_path / "data"), extract_enabled=False, summary_mode="off",
    )
    engine = LoopEngine(
        llm_client=_Fake(), registry=ToolRegistry(),
        memory=None, session=SessionStore(tmp_path / "sessions"),
        settings=settings,
    )
    # 装配点真实路径: 写 inbox 文件 → 不 monkeypatch 方法，走真实扫描
    inbox = tmp_path / "interop" / "lfl_to_dsh" / "pending"
    inbox.mkdir(parents=True)
    (inbox / "20260816-006_dsh-x.json").write_text(json.dumps({
        "id": "20260816-006", "from": "dsh", "to": "lfl",
        "topic": "notify", "body": "通道注入装配点验证", "status": "pending",
    }), encoding="utf-8")
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))

    sess = engine.session.create("interop-test") if hasattr(engine.session, "create") else None
    if sess is None:
        pytest.skip("SessionStore 无 create 接口")
    # memory 注入非空时，inbox 必须在 memory 之后（合并进 system 前缀, 追加式保持前缀稳定）
    mem = Message(role="system", content="MEM-1: 记忆片段", source=MessageSource.SYSTEM)
    out = engine._build_llm_messages(engine.session.load(sess), [mem], max_chars=200000)
    assert len(out) == 1 and out[0]["role"] == "system"  # P1-FEISHU: system 全合并进 out[0]
    content = out[0]["content"]
    assert "MEM-1" in content                 # memory 注入生效
    assert "20260816-006" in content          # inbox 注入生效（每轮必感知）
    assert content.index("20260816-006") > content.index("MEM-1")  # inbox 在 memory 之后
