

def test_truncated_receipt_tagged(monkeypatch):
    """EVO-20260820-be72efb1: 截断回执标注 ⚠️截断，声明比对感知未核验数据."""
    from llm_loop.core.message import Message, MessageSource, ToolResultStatus
    from llm_loop.feedback.validator import DeclarationValidator

    checker = DeclarationValidator(audit_dir=None)
    # 截断回执（内容含截断标记）
    msgs = [
        Message(
            role="tool", status=ToolResultStatus.SUCCESS,
            content="[输出已截断] 完整 50000 字符，仅首 4096 + 尾 1024…取全文: read_file",
            source=MessageSource.TOOL, tool_call_id="c1", tool_name="execute_command",
        )
    ]
    r = checker.check("已执行命令并查看输出", msgs)
    assert any("⚠️截断" in x for x in r.receipt_summary)


def test_discrepancy_receipt_sample_takes_latest(monkeypatch):
    """漂移修复 2026-08-29（会话 68fed5f5 实证）: 回执样本就近取样（最新3条）.

    原逻辑 receipts[:3] 引用最早回执——漂移轮被最早轮 model_catalog（身份话题）
    样本直接诱导复读。修复后取 [-3:]（最新），断言样本含最新回执。
    """
    from llm_loop.core.message import Message, MessageSource, ToolResultStatus
    from llm_loop.feedback.validator import DeclarationValidator

    checker = DeclarationValidator(audit_dir=None)
    msgs = [
        Message(role="tool", status=ToolResultStatus.SUCCESS, content="最早的model_catalog回执内容",
                source=MessageSource.TOOL, tool_call_id="c1", tool_name="model_catalog"),
        Message(role="tool", status=ToolResultStatus.SUCCESS, content="中期回执1",
                source=MessageSource.TOOL, tool_call_id="c2", tool_name="execute_command"),
        Message(role="tool", status=ToolResultStatus.SUCCESS, content="中期回执2",
                source=MessageSource.TOOL, tool_call_id="c3", tool_name="search_files"),
        Message(role="tool", status=ToolResultStatus.SUCCESS, content="最新的web_fetch回执内容",
                source=MessageSource.TOOL, tool_call_id="c4", tool_name="web_fetch"),
    ]
    r = checker.check("已执行了一个不存在的探测任务并查看结果", msgs)
    assert r.discrepancies, "不匹配声明应产生差异反馈"
    text = r.discrepancies[0]
    assert "web_fetch" in text, f"回执样本应含最新回执（就近取样），实际: {text[:200]}"
