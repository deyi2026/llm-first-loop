"""EVO-20260810-50816b30: 声明-回执校验能力陈述语义区分测试."""
from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.feedback.validator import DeclarationValidator


def _tool_msg(name: str, content: str, status=ToolResultStatus.SUCCESS) -> Message:
    return Message(
        role="tool", content=content, source=MessageSource.TOOL,
        tool_call_id="t1", status=status, tool_name=name,
    )


def test_ability_statement_skipped():
    """能力陈述（可以…执行…）不参与回执校验 → 不产生 discrepancy."""
    v = DeclarationValidator()
    answer = "我可以调用工具读取本地文件、执行 shell 命令、抓取网页内容等。"
    result = v.check(answer, [])  # 无工具回执
    assert result.consistent is True  # 能力陈述不应报不一致
    assert result.discrepancies == []


def test_completion_statement_checked():
    """行为声明（已执行…）无对应回执 → 产生 discrepancy（既有行为保留）."""
    v = DeclarationValidator()
    answer = "我已执行命令并写入文件。"
    result = v.check(answer, [])  # 无回执
    assert result.consistent is False
    assert len(result.discrepancies) == 1


def test_completion_statement_matches_receipt():
    """行为声明 + 对应回执 → 一致（keyword 匹配）."""
    v = DeclarationValidator()
    answer = "我已执行命令确认系统状态。"
    result = v.check(answer, [_tool_msg("execute_command", "执行成功，输出正常")])
    assert result.consistent is True


def test_mixed_ability_and_completion():
    """同句含能力+完成: 完成部分被校验，能力部分被跳过."""
    v = DeclarationValidator()
    answer = "我可以使用多种工具；本轮已通过 web_fetch 抓取了页面内容。"
    result = v.check(answer, [_tool_msg("web_fetch", "抓取成功，返回 HTML")])
    assert result.consistent is True
