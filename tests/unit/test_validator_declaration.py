

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
    （EVO-20261007-c1313de6 适配: 原泛化 miss 声明"已执行了一个不存在的探测任务"
    会命中工具名兜底；改用含未命中 path token 的声明保持 miss 语义。）
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
    r = checker.check("已执行 nonexistent_probe.sh 并查看结果", msgs)
    assert r.discrepancies, "不匹配声明应产生差异反馈"
    text = r.discrepancies[0]
    assert "web_fetch" in text, f"回执样本应含最新回执（就近取样），实际: {text[:200]}"


def test_nested_subagent_success_receipt_satisfies_execute_declaration():
    """subagent_result 的结构化 nested success 可证明 child execute_command 完成。"""
    from llm_loop.core.message import Message, MessageSource, ToolResultStatus
    from llm_loop.feedback.validator import DeclarationValidator

    checker = DeclarationValidator(audit_dir=None)
    msgs = [
        Message(
            role="tool",
            status=ToolResultStatus.SUCCESS,
            content="[状态: success] child_state=completed child_outcome=completed",
            source=MessageSource.TOOL,
            tool_call_id="sub-r1",
            tool_name="subagent_result",
            metadata={"verification_receipts": ["execute_command:success"]},
        )
    ]
    result = checker.check("子代理已执行命令并完成验证", msgs)
    assert result.consistent is True
    assert "nested:execute_command:success" in result.receipt_summary


def test_nested_failure_receipt_never_proves_successful_execute_declaration():
    """即使外层 subagent_result 是 success，nested failure 也不能冒充执行成功证据。"""
    from llm_loop.core.message import Message, MessageSource, ToolResultStatus
    from llm_loop.feedback.validator import DeclarationValidator

    checker = DeclarationValidator(audit_dir=None)
    msgs = [
        Message(
            role="tool",
            status=ToolResultStatus.SUCCESS,
            content="[状态: success] child_state=completed child_outcome=completed",
            source=MessageSource.TOOL,
            tool_call_id="sub-r2",
            tool_name="subagent_result",
            metadata={"verification_receipts": ["execute_command:failure"]},
        )
    ]
    result = checker.check("子代理已执行命令并完成验证", msgs)
    assert result.consistent is False
    assert "nested:execute_command:failure" not in result.receipt_summary


# ---- EVO-20261007-c1313de6: 跨语动词↔工具名匹配缺口修复回归 ----


def _exec_receipt(content: str, call_id: str = "c1"):
    from llm_loop.core.message import Message, MessageSource, ToolResultStatus

    return Message(
        role="tool", status=ToolResultStatus.SUCCESS, content=content,
        source=MessageSource.TOOL, tool_call_id=call_id, tool_name="execute_command",
    )


def test_execute_receipt_satisfies_generic_execute_declaration():
    """泛化"已执行"声明 + execute_command 成功回执 → 命中（核心缺口修复）.

    旧缺陷（DC-…b4a4fe 实证）: 动词子串路径要求回执含字面"执行"，而
    execute_command 回执标签为英文工具名 + [命令]/[退出码 0]；结构化工具名
    匹配只接受 nested 精确相等——真阳性声明被判不一致。
    """
    from llm_loop.feedback.validator import DeclarationValidator

    checker = DeclarationValidator(audit_dir=None)
    msgs = [_exec_receipt("[命令] pytest tests/unit/ -q [退出码 0] [输出] 62 passed")]
    r = checker.check("我已执行该校验", msgs)
    assert r.consistent is True, f"泛化已执行声明应命中工具名匹配，实际: {r.discrepancies}"


def test_cross_language_english_execute_declaration_matches():
    """英文声明 "executed" 同样经工具名兜底命中（跨语缺口覆盖英文动词）."""
    from llm_loop.feedback.validator import DeclarationValidator

    checker = DeclarationValidator(audit_dir=None)
    msgs = [_exec_receipt("[命令] pytest tests/unit/ -q [退出码 0]")]
    r = checker.check("I have executed the full check", msgs)
    assert r.consistent is True, f"英文 executed 声明应命中，实际: {r.discrepancies}"


def test_unmatched_path_object_blocks_toolname_fallback():
    """动词-宾语锚定: 声明含未命中的具体对象时，工具名兜底不得泛化放行.

    防松化审查点（建议 A 预留）: "已执行 X.sh"+任意 execute_command 回执若
    直接匹配，会掩盖虚假具体声明。path token 未命中必须保持 miss。
    """
    from llm_loop.feedback.validator import DeclarationValidator

    checker = DeclarationValidator(audit_dir=None)
    msgs = [_exec_receipt("[命令] ls -la [退出码 0]")]
    r = checker.check("我已执行 batch_cleanup.sh 全量清理", msgs)
    assert r.discrepancies, "含未命中 path token 的声明必须保持 miss（防泛化掩盖虚假具体声明）"


def test_blocked_receipt_never_satisfies_toolname_match():
    """BLOCKED 回执同样以工具名开头，但不得作为工具名匹配证据（状态过滤点）."""
    from llm_loop.core.message import Message, MessageSource, ToolResultStatus
    from llm_loop.feedback.validator import DeclarationValidator

    checker = DeclarationValidator(audit_dir=None)
    msgs = [
        Message(
            role="tool", status=ToolResultStatus.BLOCKED, content="危险命令已阻断",
            source=MessageSource.TOOL, tool_call_id="c1", tool_name="execute_command",
        )
    ]
    r = checker.check("我已执行该校验", msgs)
    assert r.consistent is False, "BLOCKED 回执不得证明执行成功"


def test_truncated_execute_receipt_still_satisfies_toolname_match():
    """截断标注回执前缀 `execute_command（⚠️截断…）` 仍命中工具名匹配."""
    from llm_loop.feedback.validator import DeclarationValidator

    checker = DeclarationValidator(audit_dir=None)
    msgs = [_exec_receipt("[输出已截断] 完整 50000 字符，仅首 4096 + 尾 1024…")]
    r = checker.check("我已执行该校验", msgs)
    assert r.consistent is True, f"截断成功回执仍应命中，实际: {r.discrepancies}"


def test_miss_wording_states_match_not_pool():
    """EVO-20261007-c1313de6 B: miss 判语必须是匹配级表述，不得断言池内无成功记录.

    实证冲突（DC-…b4a4fe）: 判语"均未见对应成功记录"被自己引用的
    [退出码 0] 回执样本推翻——池内有成功回执，真实情况是匹配未命中。
    """
    from llm_loop.feedback.validator import DeclarationValidator, build_discrepancy_feedback

    checker = DeclarationValidator(audit_dir=None)
    # 池内存在成功回执，声明动词（安装）不在工具关键词映射 → 匹配 miss
    msgs = [_exec_receipt("[命令] pip install --dry-run check [退出码 0]")]
    r = checker.check("我已安装生产环境的全部依赖", msgs)
    assert r.discrepancies, "未映射动词声明应产生 miss"
    text = r.discrepancies[0]
    assert "未匹配到对应记录" in text, f"判语应为匹配级表述，实际: {text[:200]}"
    assert "均未见" not in text, "不得断言池内无成功记录（池级事实断言）"
    fb = build_discrepancy_feedback(r)
    assert "未能在本轮工具成功回执中匹配到对应记录" in fb
    assert "无对应成功记录" not in fb, "反馈文案不得使用池级断言"
