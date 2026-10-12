from __future__ import annotations

from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.builtin.web_fetch import WebFetchTool
from llm_loop.tools.builtin.web_search import WebSearchTool
from llm_loop.tools.source_recovery_contract import (
    SHARED_SOURCE_RECOVERY_CONTRACT,
    SourceRecoveryKind,
    source_recovery_guidance,
)


def test_shared_contract_is_semantic_not_anti_repeat() -> None:
    text = SHARED_SOURCE_RECOVERY_CONTRACT
    assert "已有 Evidence" in text
    assert "覆盖" in text
    assert "currentness" in text
    assert "EvidenceRef" in text
    assert "控制面句柄" in text
    assert "新获取" in text
    assert "未覆盖" in text
    banned = ("never reread", "do not repeat", "禁止重读", "禁止重复", "不得重读")
    assert not any(term.casefold() in text.casefold() for term in banned)


def test_read_file_description_prefers_recovery_for_covered_current_evidence() -> None:
    desc = ReadFileTool.description
    assert SHARED_SOURCE_RECOVERY_CONTRACT in desc
    assert source_recovery_guidance(SourceRecoveryKind.PROBEABLE_FILE) in desc
    assert "offset/limit" in desc
    assert "未覆盖" in desc


def test_execute_command_description_distinguishes_snapshot_recovery_from_new_execution() -> None:
    desc = ExecuteCommandTool.description
    assert SHARED_SOURCE_RECOVERY_CONTRACT in desc
    assert source_recovery_guidance(SourceRecoveryKind.COMMAND_SNAPSHOT) in desc
    assert "历史执行 observation" in desc
    assert "新的执行" in desc


def test_web_source_descriptions_distinguish_prior_observation_from_current_remote_state() -> None:
    fetch = WebFetchTool.description
    search = WebSearchTool.description
    assert SHARED_SOURCE_RECOVERY_CONTRACT in fetch
    assert SHARED_SOURCE_RECOVERY_CONTRACT in search
    assert source_recovery_guidance(SourceRecoveryKind.WEB_FETCH) in fetch
    assert source_recovery_guidance(SourceRecoveryKind.WEB_SEARCH) in search
    assert "当前远端状态" in fetch
    assert "当前外部结果" in search
