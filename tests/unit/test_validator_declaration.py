

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
