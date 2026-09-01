"""Cognitive 认知运行时门控与注入阶段（design §2.1.2 #12 / T5-C 第 4 批）.

authority = RETRIEVAL-ONLY（冻结态下 promote 禁止）：本模块只做认知运行时
的模式门控解析（off/shadow/enforce + 冻结/名单提升）与语义检索产物的
装配接线，不拥有终止/预算/缓存职责（R9-P4-04 职责单一：semantic 类模块
无 cache 职责引用）。

冻结语义（R8.24-E E-D4 / E-2.1）：LFL_COG_ENFORCE_FREEZE（默认 on）下
①allowlist 自动 promote 恒不触发；②显式/现网 enforce 配置降 shadow
（effective mode 恒 ∈ {off, shadow}，E-G4）。恢复 promote 须走
LFL_COG_ENFORCE_FREEZE=off 且绑定 E-2.2 五条件重新审批
（cognitive-refreeze-conditions.md）。

B4-C4-01 第 1 步迁入：门控解析（mode/freeze/promote/compute_candidate/
has_existing_program）+ 冻结/名单 helpers；决策落 BuildDecision.cog_freeze。
后续步骤：state 读取/Read Barrier/投影（第 2 步）、packet 装配/telemetry
（第 3 步）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from llm_loop.core.injection_labels import InjectionLayer, detect_program_layer

if TYPE_CHECKING:
    from llm_loop.core.prompt_build import BuildDecision


def _cog_freeze_enabled() -> bool:
    """R8.24-E E-2.1: enforce 冻结开关（LFL_COG_ENFORCE_FREEZE，默认 on）.

    off/false/0/空 视为回滚通道（恢复 promote 必须绑定 E-2.2 重新审批）。
    """
    return str(os.environ.get("LFL_COG_ENFORCE_FREEZE", "1")).strip().lower() not in (
        "",
        "0",
        "false",
        "off",
    )


def _cog_allowlist_hit(settings: Any, sess: Any) -> bool:
    """Stage 2 allowlist 求值（review R3 fail-closed 强化版）.

    任何失败（空配置/相对路径/sid 空/文件缺失/OSError/超 64KiB/超 256 条/
    运行用户可写/非 UTF-8/任意有效行非法 session_id）→ False（保持 shadow）。
    每轮 build 重读——热更语义（删行下一轮生效）。

    P0-1 R3: operator-owned 边界运行时验证——运行用户对文件可写即视为
    控制面不可信（self-promote 攻击链闭合点：agent 可写文件+可见路径）。
    绝对路径是必要非充分条件；root 运行时 os.access 恒真，须配合只读
    挂载/容器部署（见 DESIGN 部署约束）。
    P0-2 R3: all-valid-or-no-promotion——任意非注释有效行非法（非单个
    文件名组件/路径穿越/NUL）→ 整份名单 False，不静默跳过坏行。
    P1-3 R3: bounded read（read(65537) 硬界）——stat 后无界 read 的
    TOCTOU 免疫，最多读 65537B；严格 UTF-8 decode。
    """
    try:
        path_s = str(getattr(settings, "cog_enforce_file", "") or "")
        if not path_s:
            return False
        if not os.path.isabs(path_s):  # P0-1: 相对路径=配置无效
            return False
        sid = str(getattr(sess, "session_id", "") or "")
        if not sid:
            return False
        if os.access(path_s, os.W_OK):  # P0-1 R3: 运行用户可写=控制面越界
            return False
        with open(path_s, "rb") as fh:  # P1-3 R3: bounded read 硬界
            raw = fh.read(65537)
        if len(raw) > 65536:
            return False
        text = raw.decode("utf-8")  # 非 UTF-8 → UnicodeDecodeError → False
        from llm_loop.core.session import _validate_session_id

        valid: list[str] = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            _validate_session_id(s)  # P0-2 R3: 非法 raise → 整份名单 False
            valid.append(s)
        if len(valid) > 256:  # P1-3: 256 有效条目硬上限
            return False
        return sid in valid
    except Exception:  # noqa: BLE001 — P0-2: fail-closed，任何异常→shadow
        return False


@dataclass(slots=True)
class CognitiveGateOutcome:
    """门控解析产物（B4-C4-01；决策同步落 BuildDecision.cog_freeze）."""

    mode: str = "shadow"  # effective mode（含 allowlist 提升/冻结降级后）
    promoted: bool = False  # 名单提升触发（冻结态恒 False）
    freeze: bool = True  # LFL_COG_ENFORCE_FREEZE 生效态
    compute_candidate: bool = False  # shadow/enforce × anchor_mode(semantic/auto)
    has_existing_program: bool = False  # history 已有 program-origin 块（R2）


def resolve_cognitive_gate(
    settings: Any,
    *,
    sess: Any,
    built: list[dict[str, Any]],
    inject_parts_present: bool,
    decision: BuildDecision | None = None,
) -> CognitiveGateOutcome:
    """COG_RUNTIME 三态门控解析（tasks 2.2/2.3；冻结/名单提升语义见模块 docstring）.

    - off 硬关前置（名单不可覆盖 P0-2）；fail-closed 全语义在 _cog_allowlist_hit；
    - quiet shadow 同构计算预判（CR-R1.1a）与 R2 持久化 program-origin 存量检测
      均在 compute 条件内（检测逻辑原样迁入，行为逐字节等价）。
    """
    _cog_mode_candidate = (
        str(getattr(settings, "cog_runtime_mode", "shadow")).strip().lower()
    )
    if _cog_mode_candidate not in ("off", "shadow", "enforce"):
        _cog_mode_candidate = "shadow"
    _cog_freeze = _cog_freeze_enabled()
    if _cog_freeze and _cog_mode_candidate == "enforce":
        _cog_mode_candidate = "shadow"  # 现网 enforce 会话降 shadow（E-G4）
    _cog_promoted = False
    if (
        _cog_mode_candidate == "shadow"
        and not _cog_freeze
        and _cog_allowlist_hit(settings, sess)
    ):
        _cog_mode_candidate = "enforce"
        _cog_promoted = True
    _cog_compute_candidate = (
        _cog_mode_candidate in ("shadow", "enforce")
        and str(getattr(settings, "cog_runtime_anchor_mode", "auto"))
        in ("semantic", "auto")
    )
    _has_existing_program = any(
        detect_program_layer(str(_m.get("content") or ""))
        not in (None, InjectionLayer.USER_INSTRUCTION)
        for _m in built
    )
    outcome = CognitiveGateOutcome(
        mode=_cog_mode_candidate,
        promoted=_cog_promoted,
        freeze=_cog_freeze,
        compute_candidate=_cog_compute_candidate,
        has_existing_program=_has_existing_program,
    )
    if decision is not None:
        # COG 冻结决策入 BuildDecision（B4-C4-01；§2.2.1 允许字段增量语义）
        decision.cog_freeze = {
            "mode": outcome.mode,
            "promoted": outcome.promoted,
            "freeze": outcome.freeze,
            "compute_candidate": outcome.compute_candidate,
            "has_existing_program": outcome.has_existing_program,
            "inject_parts_present": bool(inject_parts_present),
        }
    return outcome
