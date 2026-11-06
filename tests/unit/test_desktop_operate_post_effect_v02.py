# R-01（M1 修订批次，外部审查 2026-11-06 复核 §4 R-01）：读取 post 状态完成 ≠ 动作影响已确认。
"""红→绿契约：基线 5e295e1e0 上逐条失败（effect_state 误 confirmed）；修复后全绿。

- post AX 返回 unavailable（非异常）：dispatch_state=dispatched 保留，
  effect_state=unknown + post_observation=unavailable；post_sha256（空投影指纹）保留。
- post 可读但无动作相关后置证据（click 无回读机制）：effect_state=not_observed，
  不再无条件 confirmed。
- verified=True（type 回读成功）但 post 失效：effect_state=unknown（与 T-05 异常口径
  统一），verification.state=passed 证据保留——不因 post 失效抹掉已确立的回读证据。
- 窗口消失（get_window→None）：观测到明确后置状态但无动作级验证 → not_observed。
- 工具回执与审计同口径（post_observation 字段两处一致）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_desktop_operate_actoutcome_v01 import FakeOutcomeBackend, _runner

from llm_loop.desktop.models import ActOutcome, AxView


class _PostUnavailableBackend(FakeOutcomeBackend):
    """投递已发生后 post 观测返回 available=False（非异常）——R-01 核心场景。"""

    def ax_snapshot(self, window, depth, node_limit):
        if self.act_calls:
            return AxView(available=False, failure="ax_unavailable")
        return super().ax_snapshot(window, depth, node_limit)


class _WindowGoneBackend(FakeOutcomeBackend):
    """投递已发生后窗口消失：get_window→None。"""

    def get_window(self, window_id):
        if self.act_calls:
            return None
        return super().get_window(window_id)


def _click_kwargs(**extra):
    return {"do": "click", "window_id": 101, "target": {"ax_ref": "0.0"}, **extra}


def test_r01_post_unavailable_click_effect_unknown_not_confirmed():
    backend = _PostUnavailableBackend(set_value_outcome=ActOutcome(ok=True))
    rows: list[dict] = []
    run, _reg = _runner(backend, rows)
    dry = run(**_click_kwargs(dry_run=True))
    payload = run(**_click_kwargs(dry_run=False, confirm_token=dry["confirm_token"]))
    assert payload["applied"] is True
    assert payload["dispatch_state"] == "dispatched"  # 投递证据保留
    assert payload["effect_state"] != "confirmed"
    assert payload["effect_state"] == "unknown"
    assert payload["post_observation"] == "unavailable"
    assert payload.get("post_sha256")  # 空投影指纹仍生成（观测失败≠指纹缺席）
    assert payload["verification"]["state"] == "not_requested"
    row = rows[-1]  # 审计同口径
    assert row["effect_state"] == "unknown"
    assert row["post_observation"] == "unavailable"


def test_r01_post_readable_click_without_readback_is_not_observed():
    backend = FakeOutcomeBackend(set_value_outcome=ActOutcome(ok=True))
    rows: list[dict] = []
    run, _reg = _runner(backend, rows)
    dry = run(**_click_kwargs(dry_run=True))
    payload = run(**_click_kwargs(dry_run=False, confirm_token=dry["confirm_token"]))
    assert payload["applied"] is True
    assert payload["dispatch_state"] == "dispatched"
    # click 无回读机制：post 可读只证明观测到了后置世界，不证明点击产生了预期影响。
    assert payload["effect_state"] == "not_observed"
    assert payload["post_observation"] == "available"
    assert payload["verification"]["state"] == "not_requested"
    assert rows[-1]["effect_state"] == "not_observed"


def test_r01_verified_type_post_unavailable_unknown_but_evidence_kept():
    backend = _PostUnavailableBackend(set_value_outcome=ActOutcome(
        ok=True, verified=True, dispatch_state="dispatched",
        effect_state="confirmed", verification_state="passed",
    ))
    rows: list[dict] = []
    run, _reg = _runner(backend, rows)
    args = {"do": "type", "window_id": 101, "target": {"ax_ref": "0.1"}, "text": "hi"}
    dry = run(**args, dry_run=True)
    payload = run(**args, dry_run=False, confirm_token=dry["confirm_token"])
    assert payload["applied"] is True
    # post 失效与 post 异常同口径（T-05）：观测不可用压过回读证据 → unknown；
    # 已确立的回读证据保留在 verification.state=passed，不静默丢弃。
    assert payload["effect_state"] == "unknown"
    assert payload["post_observation"] == "unavailable"
    assert payload["verification"]["state"] == "passed"
    assert rows[-1]["effect_state"] == "unknown"
    assert rows[-1]["post_observation"] == "unavailable"


def test_r01_window_gone_without_verification_is_not_observed():
    backend = _WindowGoneBackend(set_value_outcome=ActOutcome(ok=True))
    rows: list[dict] = []
    run, _reg = _runner(backend, rows)
    dry = run(**_click_kwargs(dry_run=True))
    payload = run(**_click_kwargs(dry_run=False, confirm_token=dry["confirm_token"]))
    assert payload["applied"] is True
    assert payload["dispatch_state"] == "dispatched"
    # 观测到"窗口已消失"是明确的观测结果，但没有动作级验证 → not_observed。
    assert payload["effect_state"] == "not_observed"
    assert payload["post_observation"] == "window_gone"
    assert rows[-1]["effect_state"] == "not_observed"
