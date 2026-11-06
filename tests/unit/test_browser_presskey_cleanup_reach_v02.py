# R-02（M1 修订批次，外部审查 2026-11-06 复核 §4）：组合键部分投递的清理结果
# 不得停留在异常对象里——三种清理状态必须贯通到 compact/完整回执，模型可读。
"""红→绿契约：基线 5e295e1e0 上全部失败（compact 无 input_cleanup）；修复后全绿。

执行器段（_PressKeyPartialDispatchError.cleanup 的产生）已由
test_browser_presskey_release_v01 覆盖；本文件覆盖断点段：
adapter 捕获 → terminal receipt → operation compact/完整回执。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest
from test_browser_m2a_presskey_hover_dialog_download_v01 import FIXTURES, _Backend

from llm_loop.browser.action import BrowserActionAdapter, BrowserActionReceiptStore
from llm_loop.browser.cdp_action_host import _PressKeyPartialDispatchError
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_semantic_operation import (
    BrowserSemanticExecuteTool,
    BrowserSemanticOperationReceiptStore,
    BrowserSemanticOperationTool,
)


class _FailingActuator:
    """注入真实 _PressKeyPartialDispatchError 的 actuator（adapter 之上全真）。"""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls: list[dict] = []

    def dispatch(self, verb, physical_target, args):  # noqa: ANN001, ANN202
        self.calls.append({"verb": verb, "physical_target": physical_target, "args": args})
        raise self.exc


def _operation_with_failing_actuator(exc: Exception):
    tmp = Path(tempfile.mkdtemp())
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp / "perception"))
    backend = _Backend(FIXTURES["base"])
    actuator = _FailingActuator(exc)
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp / "actions"),
        capture_backend=backend,
        actuator=actuator,
    )
    execute = BrowserSemanticExecuteTool(
        perception=perception, action_adapter=action, session_id_getter=lambda: "s1"
    )
    operation = BrowserSemanticOperationTool(
        perception=perception,
        capture_backend=backend,
        semantic_execute=execute,
        receipt_store=BrowserSemanticOperationReceiptStore(tmp / "operation_receipts"),
        session_id_getter=lambda: "s1",
    )
    return operation, actuator


_CLEANUPS = {
    "released": {
        "pressed": 2, "released": 2, "status": "released",
        "cause": "TimeoutError", "junk_field": "must-not-leak",
    },
    "input_state_unknown": {
        "pressed": 2, "released": 0, "status": "input_state_unknown",
        "cause": "ConnectionClosed", "recovery": "reconnect_then_snapshot",
    },
    "partial_release_failed": {
        "pressed": 2, "released": 1, "status": "partial_release_failed",
        "cause": "TimeoutError", "recovery": "reconnect_then_snapshot",
    },
}


@pytest.mark.parametrize("cleanup_name", sorted(_CLEANUPS))
def test_r02_cleanup_reaches_compact_receipt_whitelisted(cleanup_name: str) -> None:
    cleanup = _CLEANUPS[cleanup_name]
    operation, actuator = _operation_with_failing_actuator(
        _PressKeyPartialDispatchError(cleanup)
    )
    result = operation.execute(do="press_key", keys="Meta+A")
    receipt = json.loads(result.content)
    assert receipt["status"] == "halted"
    assert receipt["reject_reason"] == "dispatch_error:_PressKeyPartialDispatchError"
    assert receipt["automatic_retry"] is False  # 不自动重放业务快捷键（现状保持）
    # 清理状态结构化可达（红点：修复前 compact 无此键）
    ic = receipt.get("input_cleanup")
    assert isinstance(ic, dict), f"{cleanup_name}: input_cleanup 未到达 compact 回执"
    assert ic["status"] == cleanup["status"]
    assert ic["pressed"] == cleanup["pressed"]
    assert ic["released"] == cleanup["released"]
    if "recovery" in cleanup:
        assert ic["recovery"] == cleanup["recovery"]
    # 白名单：异常携带的旁路字段不得泄漏进模型契约
    assert "junk_field" not in ic
    assert set(ic) <= {"pressed", "released", "status", "cause", "recovery"}


def test_r02_full_receipt_persisted_with_input_cleanup() -> None:
    cleanup = _CLEANUPS["input_state_unknown"]
    operation, _actuator = _operation_with_failing_actuator(
        _PressKeyPartialDispatchError(cleanup)
    )
    result = operation.execute(do="press_key", keys="Meta+A")
    receipt = json.loads(result.content)
    assert receipt["input_cleanup"]["status"] == "input_state_unknown"
    # 完整回执（receipt_ref 指向的存档）同样携带——审计与 compact 同口径
    ref = receipt.get("receipt_ref")
    assert isinstance(ref, str) and ref
