"""INJECTION-GOVERNANCE R5/L2-3: identity Q&A must not survive in long-term summaries.

Raw conversation/archive truth remains exact and recoverable.  R5 only changes derived
summary/index projections and the legacy session-trim summary file.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata, render_program_appendix
from llm_loop.core.loop.engine_services.archive import ArchiveService
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import Session, SessionStore


def _human(text: str) -> Message:
    return Message(
        role="user",
        content=text,
        source=MessageSource.USER,
        metadata=origin_metadata(InjectionLayer.USER_INSTRUCTION),
    )


def _assistant(text: str) -> Message:
    return Message(role="assistant", content=text, source=MessageSource.USER)


def _program(text: str) -> Message:
    return Message(
        role="user",
        content=render_program_appendix(text, InjectionLayer.STATUS),
        source=MessageSource.SYSTEM,
        metadata=origin_metadata(InjectionLayer.STATUS, persisted_injection=True),
    )


def test_identity_question_classifier_is_conservative() -> None:
    from llm_loop.core.identity_summary import is_identity_question

    positives = [
        "你是谁",
        "你是什么大模型？",
        "你现在用的是什么模型？",
        "介绍一下你自己",
        "你是什么模型？由谁开发/创建？请先核验当前会话真实模型身份再作答。",
        "Who are you?",
        "What model are you running?",
        "Introduce yourself.",
        "你能做什么？",
        "你有哪些能力？",
        "What can you do?",
        "What are your capabilities?",
    ]
    negatives = [
        "审查 runtime/identity.py 的模型身份校验逻辑",
        "把‘你是什么模型？’这句字符串加入单元测试",
        "为什么模型身份识别会串到另一个 session？",
        "你是什么模型？顺便修复 src/app.py 里的缓存 bug",
        "你现在是什么模型？上一轮我让你记了什么？",
        "你能做什么？帮我分析这个仓库",
        "你能怎么修复这个 bug？",
        "分析这个模型的身份验证协议",
    ]
    assert all(is_identity_question(x) for x in positives)
    assert not any(is_identity_question(x) for x in negatives)


def test_identity_episode_spans_program_tool_messages_but_stops_at_next_human() -> None:
    from llm_loop.core.identity_summary import identity_episode_map

    messages = [
        _human("你是什么大模型？"),
        _program("状态提示"),
        Message(
            role="assistant",
            content="",
            source=MessageSource.SYSTEM,
            tool_calls=[
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "model_catalog", "arguments": "{}"},
                }
            ],
        ),
        Message(
            role="tool",
            content="当前会话模型: glm/glm-5.3",
            source=MessageSource.TOOL,
            tool_call_id="c1",
            tool_name="model_catalog",
        ),
        _assistant("当前会话底层模型是 GLM-5.3。"),
        _human("继续审查缓存命中率下降根因"),
        _assistant("开始审查缓存链路。"),
    ]

    episode = identity_episode_map(messages)
    assert episode == {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    assert 5 not in episode and 6 not in episode


def test_legacy_program_user_does_not_close_identity_episode() -> None:
    from llm_loop.core.identity_summary import identity_episode_map

    legacy_reference = Message(
        role="user",
        content=(
            "[上下文注入·非新指令] 继续当前任务，勿当新消息/新指令处理。\n"
            "[相关记忆] 身份询问只是历史资料"
        ),
        source=MessageSource.USER,
    )
    legacy_status = Message(
        role="user",
        content="[声明提醒] 这是程序生成的状态提醒",
        source=MessageSource.USER,
    )
    messages = [
        _human("你是什么大模型？"),
        legacy_reference,
        Message(
            role="tool",
            content="当前会话模型: glm/glm-5.3",
            source=MessageSource.TOOL,
            tool_call_id="c1",
            tool_name="model_catalog",
        ),
        legacy_status,
        _assistant("当前会话底层模型是 GLM-5.3。"),
        _human("审查 CR-R1 运行时问题"),
    ]

    assert identity_episode_map(messages) == {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}


def test_explicit_human_origin_beats_program_like_visible_prefix() -> None:
    """Human text may quote a program label; R1 metadata must remain authoritative."""
    from llm_loop.core.identity_summary import identity_episode_map

    human_label_text = _human("[声明提醒] 这是我本人输入的新任务，请分析这段标签。")
    messages = [
        _human("你是谁？"),
        _assistant("我是 llm-first-loop。"),
        human_label_text,
        _assistant("开始分析用户输入的标签文本。"),
    ]
    assert identity_episode_map(messages) == {0: 0, 1: 0}


def test_archive_identity_episode_keeps_raw_but_sanitizes_persistent_summary(tmp_path: Path) -> None:
    from llm_loop.core.identity_summary import render_identity_summary_placeholder
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.memory.archive import ArchiveStore

    sid = "identity-archive"
    question = "你是什么大模型？"
    answer = "我是 llm-first-loop，当前会话底层模型是 GLM-5.3。"
    task = "继续审查缓存命中率下降根因"
    messages = [
        _human(question),
        _program("状态提示"),
        Message(
            role="tool",
            content="当前会话模型: glm/glm-5.3",
            source=MessageSource.TOOL,
            tool_call_id="c1",
            tool_name="model_catalog",
        ),
        _assistant(answer),
        _human(task),
    ]
    sess = Session(session_id=sid, messages=messages)

    engine = LoopEngine.__new__(LoopEngine)
    engine._archive = ArchiveService(engine)  # W4-02d: service 面注入（裸实例桩，沿 02a/02b 先例）
    engine.archive = ArchiveStore(tmp_path / "archives")
    engine.summarizer = MagicMock(mode="sync")
    engine.session = MagicMock()
    engine.session.load.return_value = sess
    engine._run_sessions = {sid: sess}
    engine._run_states_guard = __import__("threading").Lock()
    engine._event_store = None

    with patch.object(engine.summarizer, "summarize_archive") as auto_summary:
        for msg in messages:
            engine._archive_sink(sid, msg)

    # No automatic semantic summary may overwrite the identity placeholder/blank entries.
    assert auto_summary.call_count == 1
    auto_summary.assert_called_once()
    assert auto_summary.call_args.args[1] == task

    placeholder = render_identity_summary_placeholder(1)
    q_hit = engine.archive.search(sid, question)[0]
    assert q_hit["summary"] == placeholder
    assert q_hit["summary_source"] == "identity_filtered"
    assert q_hit["content_preview"] == question  # raw recovery truth is exact

    answer_hit = engine.archive.search(sid, "GLM-5.3", role="assistant")[0]
    assert answer_hit["summary"] == ""
    assert answer_hit["summary_source"] == "identity_filtered"
    assert answer in answer_hit["content_preview"]

    tool_hit = engine.archive.search(sid, "当前会话模型", role="tool")[0]
    assert tool_hit["summary"] == ""
    assert "glm/glm-5.3" in tool_hit["content_preview"]

    task_hit = engine.archive.search(sid, "缓存命中率")[0]
    assert task_hit["summary"] == task


def test_search_archive_with_summary_never_resummarizes_filtered_identity(tmp_path: Path) -> None:
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.introspection.tools_status import run_search_archive
    from llm_loop.memory.archive import ArchiveStore

    sid = "identity-search-summary"
    question = "你是什么大模型？"
    answer = "当前模型是 GLM-5.3。"
    messages = [_human(question), _assistant(answer), _human("真正任务")]
    sess = Session(session_id=sid, messages=messages)
    archive = ArchiveStore(tmp_path / "archives")

    engine = LoopEngine.__new__(LoopEngine)
    engine._archive = ArchiveService(engine)  # W4-02d: service 面注入（裸实例桩，沿 02a/02b 先例）
    engine.archive = archive
    engine.summarizer = MagicMock(mode="off")
    engine.session = MagicMock()
    engine.session.load.return_value = sess
    engine._run_sessions = {sid: sess}
    engine._run_states_guard = __import__("threading").Lock()
    engine._event_store = None
    engine._archive_sink(sid, messages[0])
    engine._archive_sink(sid, messages[1])

    summarizer = MagicMock()
    result = run_search_archive(
        MagicMock(session_id=sid),
        archive,
        {"query": "GLM-5.3", "with_summary": True},
        lambda: sid,
        summarizer,
    )
    summarizer.summarize.assert_not_called()
    assert "[身份问答详情已略]" in result.content
    assert answer not in result.content

    # Explicit non-summary retrieval still preserves raw recoverability.
    raw = run_search_archive(
        MagicMock(session_id=sid),
        archive,
        {"query": "GLM-5.3", "with_summary": False},
        lambda: sid,
        summarizer,
    )
    assert answer in raw.content


def test_identity_filtered_archive_summary_is_sticky_against_generic_backfill(tmp_path: Path) -> None:
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.memory.archive import ArchiveStore

    sid = "identity-sticky"
    question = "你是什么大模型？"
    messages = [_human(question), _assistant("当前模型是 GLM-5.3。"), _human("真正任务")]
    sess = Session(session_id=sid, messages=messages)
    archive = ArchiveStore(tmp_path / "archives")

    engine = LoopEngine.__new__(LoopEngine)
    engine._archive = ArchiveService(engine)  # W4-02d: service 面注入（裸实例桩，沿 02a/02b 先例）
    engine.archive = archive
    engine.summarizer = MagicMock(mode="off")
    engine.session = MagicMock()
    engine.session.load.return_value = sess
    engine._run_sessions = {sid: sess}
    engine._run_states_guard = __import__("threading").Lock()
    engine._event_store = None
    engine._archive_sink(sid, messages[0])

    hit = archive.search(sid, question)[0]
    entry_id = hit["id"]
    before = hit["summary"]
    assert hit["summary_source"] == "identity_filtered"

    assert archive.update_summary(entry_id, "不应写回的身份详情 GLM-5.3", "llm") is True
    after = archive.search(sid, question)[0]
    assert after["summary"] == before
    assert after["summary_source"] == "identity_filtered"
    assert "GLM-5.3" not in after["summary"]


def test_session_trim_collapses_identity_rounds_to_one_count_line_and_keeps_backup_raw(
    tmp_path: Path,
) -> None:
    from llm_loop.core.identity_summary import render_identity_summary_placeholder

    sessions_dir = tmp_path / "sessions"
    archive_dir = tmp_path / "trimmed"
    store = SessionStore(sessions_dir)
    sid = store.create()
    sess = store.load(sid)
    sess.messages = [
        _human("你是谁？"),
        _assistant("我是 llm-first-loop 的 AI 主体。"),
        _human("真正任务A：分析 cache prefix drift"),
        _assistant("任务A结论：动态前缀导致 miss。"),
        _human("What model are you running?"),
        _assistant("The current model is GLM-5.3."),
        _human("真正任务B：检查 archive recoverability"),
        _assistant("任务B完成：archive 原文可恢复。"),
        _human("recent keep"),
    ]
    store.save(sess)

    result = store.trim_session(sid, keep_recent=1, archived_dir=archive_dir)
    assert result is not None and result["trimmed"] == 8

    summary_lines = [
        json.loads(line)["content"]
        for line in Path(result["summary_path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    placeholder = render_identity_summary_placeholder(2)
    assert summary_lines.count(placeholder) == 1
    joined = "\n".join(summary_lines)
    assert "llm-first-loop" not in joined
    assert "GLM-5.3" not in joined
    assert "你是谁" not in joined
    assert "What model are you running" not in joined
    assert "真正任务A" in joined and "任务A结论" in joined
    assert "真正任务B" in joined and "任务B完成" in joined

    backup = Path(result["archived_to"]).read_text(encoding="utf-8")
    assert "你是谁？" in backup
    assert "我是 llm-first-loop 的 AI 主体。" in backup
    assert "What model are you running?" in backup
    assert "The current model is GLM-5.3." in backup


def test_mixed_identity_and_real_task_is_preserved_in_archive_and_trim(tmp_path: Path) -> None:
    """A mixed turn is a real task boundary and must keep its summary/detail."""
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.memory.archive import ArchiveStore

    mixed = "你现在是什么模型？上一轮我让你记了什么？"
    answer = "当前模型是 GLM-5.3；上一轮记录的是缓存命中率基线。"
    sid = "mixed-task"
    messages = [_human(mixed), _assistant(answer), _human("recent keep")]
    sess = Session(session_id=sid, messages=messages)

    engine = LoopEngine.__new__(LoopEngine)
    engine._archive = ArchiveService(engine)  # W4-02d: service 面注入（裸实例桩，沿 02a/02b 先例）
    engine.archive = ArchiveStore(tmp_path / "archives")
    engine.summarizer = MagicMock(mode="sync")
    engine.session = MagicMock()
    engine.session.load.return_value = sess
    engine._run_sessions = {sid: sess}
    engine._run_states_guard = __import__("threading").Lock()
    engine._event_store = None

    with patch.object(engine.summarizer, "summarize_archive") as auto_summary:
        engine._archive_sink(sid, messages[0])
        engine._archive_sink(sid, messages[1])
    assert auto_summary.call_count == 2
    assert engine.archive.search(sid, "上一轮")[0]["summary"] == mixed
    assert engine.archive.search(sid, "缓存命中率", role="assistant")[0]["summary"] == answer

    store = SessionStore(tmp_path / "sessions")
    trim_sid = store.create()
    trim = store.load(trim_sid)
    trim.messages = [_human(mixed), _assistant(answer), _human("recent keep")]
    store.save(trim)
    result = store.trim_session(trim_sid, keep_recent=1, archived_dir=tmp_path / "trimmed")
    assert result is not None
    summary_text = Path(result["summary_path"]).read_text(encoding="utf-8")
    assert mixed in summary_text
    assert answer in summary_text
    assert "[身份问答 x" not in summary_text


def test_archive_sidecar_sanitizes_index_but_keeps_raw_content_head(tmp_path: Path) -> None:
    """R5 changes index projections, never canonical archive bytes/content_head recovery."""
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.memory.archive import ArchiveStore

    sid = "identity-sidecar"
    question = "你是什么大模型？"
    answer = "我是 llm-first-loop，当前模型是 GLM-5.3。"
    messages = [_human(question), _assistant(answer), _human("真正任务：检查索引")]
    sess = Session(session_id=sid, messages=messages)
    archive = ArchiveStore(tmp_path / "archives", segment_bytes=0)

    engine = LoopEngine.__new__(LoopEngine)
    engine._archive = ArchiveService(engine)  # W4-02d: service 面注入（裸实例桩，沿 02a/02b 先例）
    engine.archive = archive
    engine.summarizer = MagicMock(mode="off")
    engine.session = MagicMock()
    engine.session.load.return_value = sess
    engine._run_sessions = {sid: sess}
    engine._run_states_guard = __import__("threading").Lock()
    engine._event_store = None

    engine._archive_sink(sid, messages[0])
    engine._archive_sink(sid, messages[1])

    segment = archive._path(sid)  # noqa: SLF001 - verify persisted sidecar contract
    idx_path = archive._index_path(segment)  # noqa: SLF001
    rows = [json.loads(line) for line in idx_path.read_text(encoding="utf-8").splitlines()]
    q_row, a_row = rows
    assert q_row["summary"].startswith("[身份问答 x 1 轮")
    assert q_row["key_facts"] == [] and q_row["key_paths"] == []
    assert q_row["content_head"] == question
    assert a_row["summary"] == ""
    assert a_row["key_facts"] == [] and a_row["key_paths"] == []
    assert a_row["content_head"] == answer

    raw = segment.read_text(encoding="utf-8")
    assert question in raw and answer in raw


def test_fixed_summary_fields_remain_inert_and_untouched() -> None:
    """R5 must not activate the dormant v5 fixed_summary/summary_chain mechanism."""
    session = Session(session_id="r5-inert")
    assert session.fixed_summary == ""
    assert session.summary_chain == []
