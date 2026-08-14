"""集成测试: FakeLLM 完整闭环（design.md §2.5.2 集成部分 / FR-LOOP 系列）.

覆盖: 最小闭环、工具反馈子循环、轮数上限、会话恢复、声明-回执更正、
架构自省查询+修正。
"""

from __future__ import annotations

from llm_loop.core.message import ToolCall


def _read_file_call(path: str, tc_id: str = "call_1") -> ToolCall:
    return ToolCall(id=tc_id, name="read_file", arguments={"path": path})


def test_full_loop_with_tool_call(build_test_engine, tmp_path):
    """FR-LOOP-01/02: 用户消息 → 工具调用 → 工具反馈 → 最终回答."""
    f = tmp_path / "hello.txt"
    f.write_text("你好，世界！", encoding="utf-8")
    engine, fake = build_test_engine(
        [
            {"tool_calls": [_read_file_call(str(f))]},
            {"content": "文件内容是：你好，世界！"},
        ]
    )
    sid = engine.session.create()
    result = engine.run(sid, "请读取 hello.txt")
    assert result.final_answer
    assert "你好，世界" in result.final_answer
    assert result.rounds == 2
    assert len(result.tool_calls) == 1
    # 工具消息正确落库（tool_call_id 绑定）
    sess = engine.session.load(sid)
    tool_msgs = [m for m in sess.messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "call_1"


def test_direct_answer_no_tool(build_test_engine):
    """无工具调用 → 直接真诚回答."""
    engine, fake = build_test_engine([{"content": "我是 AI 助手。"}])
    sid = engine.session.create()
    result = engine.run(sid, "你好")
    assert result.final_answer == "我是 AI 助手。"
    assert result.tool_calls == []


def test_tool_feedback_sub_loop(build_test_engine, tmp_path):
    """FR-LOOP-04: 工具消息作为独立消息再理解（FakeLLM 收到 tool 消息序列）."""
    f = tmp_path / "a.txt"
    f.write_text("内容A", encoding="utf-8")
    engine, fake = build_test_engine(
        [
            {"tool_calls": [_read_file_call(str(f), "call_a")]},
            {"content": "读取完成，内容是 内容A"},
        ]
    )
    sid = engine.session.create()
    engine.run(sid, "读 a.txt")
    # 第二次调用应包含 tool 消息（tool_call_id 绑定）
    second_call = fake.calls[1]["messages"]
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "call_a" for m in second_call)


def test_max_iterations_honest_end(build_test_engine):
    """循环无进展 → 达轮数上限如实结束."""
    engine, fake = build_test_engine(
        [{"tool_calls": [_read_file_call("/nonexistent/x.txt", f"call_{i}")]} for i in range(15)]
    )
    object.__setattr__(engine.settings, "max_iterations", 3)
    sid = engine.session.create()
    result = engine.run(sid, "读文件")
    assert "已达轮数上限" in result.final_answer


def test_session_restart_recovery(build_test_engine, tmp_path):
    """DFX-REL-03: 落盘 → 重建引擎 → 恢复历史继续对话."""
    f = tmp_path / "s.txt"
    f.write_text("持久内容", encoding="utf-8")
    engine, fake = build_test_engine(
        [
            {"tool_calls": [_read_file_call(str(f))]},
            {"content": "文件内容: 持久内容"},
            {"content": "基于历史继续: 你好"},
        ]
    )
    sid = engine.session.create()
    engine.run(sid, "读 s.txt")
    # 重建引擎（新 SessionStore 读同一目录）
    engine2, fake2 = build_test_engine([{"content": "继续回答"}])
    result2 = engine2.run(sid, "你好")
    assert result2.final_answer == "继续回答"
    # 历史应保留（跨 run 消息累计）
    sess = engine2.session.load(sid)
    assert any("持久内容" in m.content for m in sess.messages if m.role == "tool")


def test_declaration_discrepancy_correction(build_test_engine):
    """T38: 声明"已写入"无回执 → 轻量提醒（不重入循环）+ verification_note 记录差异."""
    engine, fake = build_test_engine(
        [
            {"content": "我已写入文件 output.txt"},
        ]
    )
    sid = engine.session.create()
    result = engine.run(sid, "写文件")
    # 不一致如实反馈（FR-FBK-01 保留）：verification_note 记录差异
    assert result.verification_note is not None
    assert "不符" in result.verification_note
    # 最终回答直接输出（不再强制更正重入）
    assert result.final_answer == "我已写入文件 output.txt"
    # 会话中注入一条 [声明提醒]（如实提示，不重入）
    sess = engine.session.load(sid)
    assert any("[声明提醒]" in m.content for m in sess.messages)


def test_architecture_status_and_correction_loop(build_test_engine, tmp_path):
    """AI-serving: LLM 先查架构状态 → 依据状态调 adjust_strategy → 循环继续且修正生效."""
    engine, fake = build_test_engine(
        [
            {"tool_calls": [ToolCall(id="c1", name="architecture_status", arguments={})]},
            {
                "tool_calls": [
                    ToolCall(
                        id="c2",
                        name="adjust_strategy",
                        arguments={"strategy": {"max_iterations": 15}},
                    )
                ]
            },
            {"content": "已调整策略。"},
        ]
    )
    sid = engine.session.create()
    result = engine.run(sid, "请查看架构状态并调整策略")
    assert result.final_answer
    # 修正生效: 策略参数已更新
    assert engine.correction_ctx.strategy.get("max_iterations") == 15
    # 工具轨迹包含两次修正工具调用
    names = [t["name"] for t in result.tool_calls]
    assert "architecture_status" in names
    assert "adjust_strategy" in names


def test_catastrophic_block_in_loop(build_test_engine):
    """FR-SAFE: LLM 声明灾难性命令 → blocked 工具消息回传（不执行）."""
    engine, fake = build_test_engine(
        [
            {
                "tool_calls": [
                    ToolCall(id="c1", name="execute_command", arguments={"command": "rm -rf /"})
                ]
            },
            {"content": "命令被安全阻断，我改用安全方案。"},
        ]
    )
    sid = engine.session.create()
    engine.run(sid, "清空磁盘")
    sess = engine.session.load(sid)
    tool_msgs = [m for m in sess.messages if m.role == "tool"]
    assert tool_msgs
    assert tool_msgs[-1].status.value == "blocked"
    assert "安全硬阻断" in tool_msgs[-1].content


def test_memory_persist_across_runs(build_test_engine):
    """FR-MEM: 回答含记忆块 → 沉淀 → 后续检索回传."""
    engine, fake = build_test_engine(
        [
            {
                "content": (
                    "好的。\n"
                    '[[memory]] {"type": "fact", "content": "用户喜欢数字 7", "keywords": ["数字", "7"]} [[/memory]]'
                )
            },
            {"content": "我记得你喜欢数字 7。"},
        ]
    )
    sid = engine.session.create()
    engine.run(sid, "记住我喜欢 7")
    assert engine.memory.count() >= 1
    # 第二轮: 检索到记忆（FakeLLM 第二次调用应含 [相关记忆]）
    engine.run(sid, "我喜欢几来着？")
    second_call = fake.calls[-1]["messages"]
    assert any("[相关记忆]" in str(m.get("content", "")) for m in second_call)


def test_search_archive_in_loop_after_compression(build_test_engine):
    """T22/T23 集成: 上下文压缩后 AI 通过 search_archive 检索找回被压缩历史."""
    engine, fake = build_test_engine(
        [
            {
                "tool_calls": [
                    ToolCall(
                        id="c1", name="search_archive", arguments={"query": "关键信息 SECRET_TOKEN"}
                    )
                ]
            },
            {"content": "已找回被压缩的关键信息: SECRET_TOKEN 相关内容。"},
        ]
    )
    # 压缩历史预算: 第一条大消息会被压缩另存
    object.__setattr__(engine.settings, "history_max_chars", 300)
    sid = engine.session.create()
    # 先跑一轮写入大消息并触发压缩（第二轮 messages 超预算 → 压缩）
    big_text = "用户要求处理 data/report.txt，包含关键信息 SECRET_TOKEN，" + "填充" * 200
    result = engine.run(sid, big_text)
    # 压缩档案中应有被压缩的内容（原文完整另存）
    assert engine.archive is not None
    hits = engine.archive.search(sid, "SECRET_TOKEN")
    assert len(hits) >= 1, "压缩档案应另存被压缩的关键信息（信息零丢失）"
    # search_archive 工具在循环中被调用
    names = [t["name"] for t in result.tool_calls]
    assert "search_archive" in names
    assert "找回" in result.final_answer


def test_search_records_tool_accessible(build_test_engine):
    """T23: search_records 工具注册且可被 LLM 调用（统一检索入口）."""
    engine, fake = build_test_engine(
        [
            {
                "tool_calls": [
                    ToolCall(
                        id="c1",
                        name="search_records",
                        arguments={"kind": "memory", "query": "蓝色"},
                    )
                ]
            },
            {"content": "已检索记忆记录。"},
        ]
    )
    sid = engine.session.create()
    result = engine.run(sid, "检索一下记忆")
    names = [t["name"] for t in result.tool_calls]
    assert "search_records" in names
    assert "检索" in result.final_answer


def test_cross_session_memory_reuse(build_test_engine):
    """FR-P1-SES-05: 会话 A 沉淀 → 会话 B 理解阶段检索命中（跨会话复用）."""
    engine, fake = build_test_engine(
        [
            {
                "content": (
                    "好的。\n"
                    '[[memory]] {"type": "fact", "content": "跨会话关键词 XSKEY", "keywords": ["XSKEY"]} [[/memory]]'
                )
            },
            {"content": "基于记忆回答。"},
        ]
    )
    sid_a = engine.session.create()
    engine.run(sid_a, "记住 XSKEY")
    assert engine.memory.count() >= 1
    # 新会话 B
    sid_b = engine.session.create()
    engine.run(sid_b, "XSKEY 相关的内容是什么")
    # 第二次调用应注入 [相关记忆]
    last_call = fake.calls[-1]["messages"]
    assert any("[相关记忆]" in str(m.get("content", "")) for m in last_call)


def test_session_switch_and_continue(build_test_engine):
    """FR-P1-SES-03: 指定会话继续对话，历史完整恢复."""
    engine, fake = build_test_engine(
        [
            {"tool_calls": [ToolCall(id="c1", name="read_file", arguments={"path": "/tmp/x.txt"})]},
            {"content": "第一次回答"},
            {"content": "第二次回答（历史已恢复）"},
        ]
    )
    sid = engine.session.create()
    engine.run(sid, "第一条消息")
    # 复用同一会话继续（历史恢复：第二轮 messages 含第一条用户消息）
    result2 = engine.run(sid, "第二条消息")
    assert result2.final_answer
    sess = engine.session.load(sid)
    assert len(sess.messages) >= 4  # 两轮消息累积


def test_search_records_memory_extract_kind(build_test_engine):
    """T33: search_records kind=memory_extract 命中提取记录."""
    engine, fake = build_test_engine(
        [
            {
                "tool_calls": [
                    ToolCall(
                        id="c1",
                        name="search_records",
                        arguments={"kind": "memory_extract", "query": "manual"},
                    )
                ]
            },
            {"content": "已检索提取记录。"},
        ]
    )
    # 先手动触发一次提取（写审计）
    sid = engine.session.create()
    if engine.extractor is not None:
        engine.extractor.extract_session(sid, trigger="manual")
    result = engine.run(sid, "检索提取记录")
    names = [t["name"] for t in result.tool_calls]
    assert "search_records" in names


def test_archive_semantic_retrieval(build_test_engine):
    """T35: 压缩档案语义检索（HashEmbedder 语义相关命中）."""
    engine, fake = build_test_engine(
        [
            {
                "tool_calls": [
                    ToolCall(id="c1", name="search_archive", arguments={"query": "喜欢的色彩"})
                ]
            },
            {"content": "已通过语义检索找回。"},
        ]
    )
    # 手动注入一条语义相关的档案（内容含"蓝色"但 query 用"色彩"）
    assert engine.archive is not None
    engine.archive.archive(
        sid := "s-sem", role="user", source="user", content="用户声明他喜欢蓝色", tool_name="x"
    )
    # 语义检索命中（HashEmbedder 下"色彩"与"蓝色"内容向量相关）
    from llm_loop.memory.embedder import HashEmbedder
    from llm_loop.memory.retriever import SemanticRetriever

    retriever = SemanticRetriever(HashEmbedder(), archive_dir="/tmp/llm-arch-test")
    # 直接验证语义检索器能召回
    result = retriever.search(
        "喜欢的色彩", top_k=3, scope="archive", session_id=sid, archive=engine.archive
    )
    contents = [h.get("content", "") for h in result.entries]
    assert any("蓝色" in c for c in contents)


def test_eval_trigger_milestone_injected(build_test_engine):
    """T65: run 完成里程碑 → 注入 [自我评估提醒]（仅提示不强制，EVAL-03）."""
    from llm_loop.introspection.evaluator import EvalTriggerDetector

    engine, fake = build_test_engine([{"content": "我是 AI 助手。"}])
    # 注入触发检测器（里程碑必触发）
    engine.loop_signal_detector._eval_trigger_detector = EvalTriggerDetector(interval_rounds=9999)
    sid = engine.session.create()
    result = engine.run(sid, "你好")
    assert result.final_answer == "我是 AI 助手。"  # 不阻塞回答输出（DFX-PERF-06）
    sess = engine.session.load(sid)
    reminders = [m for m in sess.messages if m.role == "system" and "自我评估" in m.content]
    assert len(reminders) >= 1
    assert "self_evaluate" in reminders[0].content


def test_eval_trigger_periodic_injected(build_test_engine, tmp_path):
    """T65: 定期触发（rounds % interval == 0）→ 每轮末注入提醒."""
    from llm_loop.introspection.evaluator import EvalTriggerDetector

    f = tmp_path / "p.txt"
    f.write_text("内容P", encoding="utf-8")
    engine, fake = build_test_engine(
        [
            {"tool_calls": [_read_file_call(str(f), "call_p1")]},
            {"tool_calls": [_read_file_call(str(f), "call_p2")]},
            {"content": "最终回答"},
        ]
    )
    # interval=2 → rounds=2 触发定期提醒
    engine.loop_signal_detector._eval_trigger_detector = EvalTriggerDetector(interval_rounds=2)
    sid = engine.session.create()
    result = engine.run(sid, "多轮任务")
    assert result.final_answer == "最终回答"
    assert result.rounds >= 2  # 提醒注入不改变回答流程
    sess = engine.session.load(sid)
    reminders = [m for m in sess.messages if m.role == "system" and "自我评估" in m.content]
    assert len(reminders) >= 1
    assert "self_evaluate" in reminders[0].content


def test_eval_trigger_remind_disabled(build_test_engine):
    """T65: SELF_EVAL_REMIND_ENABLED=0 → 不注入提醒（可配置关闭）."""
    from dataclasses import replace

    from llm_loop.introspection.evaluator import EvalTriggerDetector

    engine, fake = build_test_engine([{"content": "我是 AI 助手。"}])
    engine.loop_signal_detector._eval_trigger_detector = EvalTriggerDetector(interval_rounds=1)
    # 关闭提醒（Settings 为 frozen，用 replace 构造新实例；同步更新 detector 注入的 settings）
    engine.settings = replace(engine.settings, self_eval_remind_enabled=False)
    engine.loop_signal_detector._settings = engine.settings
    sid = engine.session.create()
    engine.run(sid, "你好")
    sess = engine.session.load(sid)
    reminders = [m for m in sess.messages if m.role == "system" and "自我评估" in m.content]
    assert reminders == []


def test_multi_tool_round_reasoning_roundtrip(build_test_engine):
    """M20 T133（THK-04 门禁）: 多轮工具循环中 reasoning_content 完整回传（防 400）."""
    from llm_loop.core.message import ToolCall

    engine, fake = build_test_engine(
        [
            {
                "content": "先读取文件。",
                "tool_calls": [ToolCall(id="c1", name="read_file", arguments={"path": "/x"})],
                "reasoning_content": "第一轮思考链",
            },
            {"content": "最终回答", "reasoning_content": "第二轮思考链"},
        ]
    )
    sid = engine.session.create()
    result = engine.run(sid, "读文件并回答")
    assert result.final_answer == "最终回答"
    # 第二轮 messages 中第一轮 assistant 消息应含 reasoning_content（回传链）
    assert len(fake.calls) >= 2
    second_round_messages = fake.calls[1]["messages"]
    first_assistant = [m for m in second_round_messages if m.get("role") == "assistant"][0]
    assert first_assistant.get("reasoning_content") == "第一轮思考链"
    assert first_assistant.get("tool_calls"), "工具声明应保留"


def test_multi_tool_round_no_reasoning_zero_regression(build_test_engine):
    """M20 T133: 无 reasoning_content → 第二轮 messages 无该键（FakeLLM 零回归）."""
    from llm_loop.core.message import ToolCall

    engine, fake = build_test_engine(
        [
            {
                "content": "先读取文件。",
                "tool_calls": [ToolCall(id="c1", name="read_file", arguments={"path": "/x"})],
            },
            {"content": "最终回答"},
        ]
    )
    sid = engine.session.create()
    result = engine.run(sid, "读文件并回答")
    assert result.final_answer == "最终回答"
    second_round_messages = fake.calls[1]["messages"]
    first_assistant = [m for m in second_round_messages if m.get("role") == "assistant"][0]
    assert "reasoning_content" not in first_assistant  # 缺失态零回归


def _extract_names(sess):
    """提取 assistant 工具声明名（落盘格式 {function:{name}} 与对象格式兼容）."""
    names = []
    for m in sess.messages:
        if m.role == "assistant" and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                if isinstance(tc, dict):
                    fn = tc.get("function") or {}
                    n = fn.get("name", "") if isinstance(fn, dict) else ""
                else:
                    n = getattr(tc, "name", "")
                if n:
                    names.append(n)
    return names


def test_exec_read_file_must_task(build_test_engine, tmp_path):
    """M21 T145 FakeLLM 兜底: must 型任务下 read_file 声明 → 程序正确执行回传 + 回答含内容.

    兜底职责（12.8.7）: 验证"当 LLM 声明 read_file 时程序正确执行回传"，不承担"AI 是否会用工具"的行为验证。
    """

    f = tmp_path / "exec_task_01.txt"
    f.write_text("LLMFIRST-M21-EXEC-FIXTURE-7F3C 冷却液阈值 128.5 升", encoding="utf-8")
    engine, fake = build_test_engine(
        [
            {"tool_calls": [_read_file_call(str(f), "call_r1")]},
            {"content": "该文件写道：冷却液阈值 128.5 升"},
        ]
    )
    sid = engine.session.create()
    result = engine.run(sid, f"请读取 {f} 的内容并告诉我它写了什么")
    assert "128.5" in result.final_answer
    # read_file 回执 success（落盘断言）
    sess = engine.session.load(sid)
    tool_msgs = [m for m in sess.messages if m.role == "tool"]
    assert tool_msgs, "无 tool 回执"
    assert any("success" in str(getattr(m, "status", "")) for m in tool_msgs)


def test_exec_failure_self_correct(build_test_engine, tmp_path):
    """M21 T147 FakeLLM 兜底: 失败→自纠错响应序列（≥2 次工具调用 + 失败回执保留）."""
    from llm_loop.core.message import ToolCall

    real = tmp_path / "read_me.txt"
    real.write_text("LLMFIRST-M21-EXEC-FIXTURE-BETA 压缩阈值 0.82", encoding="utf-8")
    missing = tmp_path / "missing_file.txt"  # 不创建
    engine, fake = build_test_engine(
        [
            {"tool_calls": [_read_file_call(str(missing), "call_f1")]},
            {
                "tool_calls": [
                    ToolCall(
                        id="call_l2",
                        name="execute_command",
                        arguments={"command": f"ls {tmp_path}"},
                    )
                ]
            },
            {"tool_calls": [_read_file_call(str(real), "call_f3")]},
            {"content": "读取到：压缩阈值 0.82"},
        ]
    )
    sid = engine.session.create()
    result = engine.run(
        sid, f"请先读取 {missing} 的内容；如果不存在，列出 {tmp_path} 目录文件并读取实际存在的。"
    )
    assert "0.82" in result.final_answer
    sess = engine.session.load(sid)
    # 工具序列 ≥2（多步闭环）: 落盘格式 {function: {name}} 与对象格式兼容
    seq = _extract_names(sess)
    assert len(seq) >= 2, f"工具序列 <2: {seq}"
    # 失败回执如实保留
    tool_msgs = [m for m in sess.messages if m.role == "tool"]
    fail_msgs = [m for m in tool_msgs if "不存在" in str(m.content)]
    assert fail_msgs, "失败回执未保留"


def test_exec_multi_step_closure(build_test_engine, tmp_path):
    """M21 T148 FakeLLM 兜底: 多步任务（列目录→读文件）→ 工具序列 ≥2 + 闭环."""
    from llm_loop.core.message import ToolCall

    f1 = tmp_path / "a.txt"
    f1.write_text("LLMFIRST-M21-EXEC-FIXTURE-7F3C 冷却液阈值 128.5 升", encoding="utf-8")
    engine, fake = build_test_engine(
        [
            {
                "tool_calls": [
                    ToolCall(
                        id="call_m1",
                        name="execute_command",
                        arguments={"command": f"ls {tmp_path}"},
                    )
                ]
            },
            {"tool_calls": [_read_file_call(str(f1), "call_m2")]},
            {"content": "a.txt 写道：冷却液阈值 128.5 升"},
        ]
    )
    sid = engine.session.create()
    result = engine.run(sid, f"请列出 {tmp_path} 目录文件，读取其中某个文件内容并告诉我它写了什么")
    assert "128.5" in result.final_answer
    sess = engine.session.load(sid)
    seq = _extract_names(sess)
    assert len(seq) >= 2, f"多步闭环失败: {seq}"
