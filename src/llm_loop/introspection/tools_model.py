"""model_catalog + switch_model 工具实现（M48 / design §5.3）.

- MODEL_CATALOG_TOOL_DEF / SWITCH_MODEL_TOOL_DEF: LLM 可见工具 schema（修正框架复用）
- run_model_catalog: 只读，列目录 + 当前会话模型 + degraded 标注
- run_switch_model: 写操作，改 sess.model_override + 审计落盘 + 如实回执

失败路径按 design §三 原则 2 如实反馈（resolve 失败 / key 缺失 / 歧义），禁止静默降级；
model="default" 视为清除 override 回装配默认（design §5.3 行为 5）。

复用 corrections.py 现有审计通道（self_correction_log.jsonl），扩展记录 who/when/from→to/reason.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.llm.pool import ModelClientPool

MODEL_CATALOG_TOOL_DEF: dict = {
    "name": "model_catalog",
    "description": (
        "列出当前可用的模型目录（provider/模型/上下文窗口/思考支持/成本档）及当前会话所用模型。"
        "何时用: 判断当前任务是否需要更强/更便宜的模型，或当前模型异常需要换模型前先用本工具查候选。"
        "何时不用: 已知要用哪个模型时直接用 switch_model。"
        "失败对策: 注册表未配置时如实返回单 provider 现状（不伪造多 provider）。"
    ),
    "parameters": {"type": "object", "properties": {}},
}


SWITCH_MODEL_TOOL_DEF: dict = {
    "name": "switch_model",
    "description": (
        "切换当前会话使用的模型（provider/model 或裸模型名；model='default' 清除覆盖回默认）。"
        "何时用: 当前模型不适合任务（如需要更强推理/需要本地离线/成本约束），"
        "或当前模型连续异常经判断为模型侧问题时。"
        "何时不用: 工具失败应先用 retry_tool；参数问题应用 adjust_strategy。"
        "失败对策: 模型不在目录/provider key 缺失/裸名歧义会如实返回原因，请基于回执选择其他模型或说明。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "description": "目标模型（'provider/model' 或裸模型名；'default' 清除覆盖）",
            },
            "reason": {
                "type": "string",
                "description": "切换原因（审计落盘，必填）",
            },
        },
        "required": ["model", "reason"],
    },
}


@dataclass(frozen=True)
class _SwitchOutcome:
    """switch_model 内部结果（frozen 类型安全，外部仅消费 ToolResult）."""

    from_model: str
    to_model: str  # "default" 表示清除 override 回默认
    reason: str
    thinking_supported: bool
    # True 表示成功切换（已修改 sess.model_override + 审计落盘）；
    # False 表示 resolve/client_params 失败（未修改状态，如实回执）
    changed: bool


def run_model_catalog(
    ctx: Any,
    pool: ModelClientPool | None,
    session_override: str | None,
) -> ToolResult:
    """model_catalog: 列出可用模型 + 当前会话模型 + degraded 标注（只读）.

    零回归: 未配置注册表（registry 仅含单 provider）时如实返回单 provider 现状,
    不伪造多 provider 列表.
    """
    if pool is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                "[工具不可用] 事实: 模型客户端池未装配（pool=None）。"
                "原因: 程序未注入 ModelClientPool；model_catalog 工具不可用。"
                "建议: 检查装配（factory.build_engine 应已注入）。"
            ),
            tool_call_id="",
            tool_name="model_catalog",
        )

    registry = pool.registry
    default_model = pool.get_default_model()
    current_model = session_override if session_override else default_model
    current_source = "会话覆盖" if session_override else "默认装配"

    lines: list[str] = []
    lines.append(f"[状态: 成功] 当前会话模型: {current_model}（{current_source}）")
    if registry.degraded:
        lines.append(f"[degraded] {registry.degraded_reason}")
    lines.append("可用模型目录:")
    # 按 provider 分组列出, 标记当前会话模型所在 provider
    try:
        if session_override:
            cur_pid, _ = registry.resolve(session_override)
        else:
            cur_pid = ""
    except ValueError:
        cur_pid = ""
    for pid, spec in registry.providers.items():
        lines.append(f"  [{pid}] base_url={spec.base_url}")
        for mid, mspec in spec.models.items():
            thinking = "✓" if mspec.thinking else "✗"
            is_current = pid == cur_pid and (
                (session_override and mid in session_override)
                or (not session_override and mid == default_model)
            )
            mark = " ← 当前" if is_current else ""
            caps = []
            if mspec.reasoning:
                caps.append("reasoning")
            if mspec.long_context:
                caps.append("long_context")
            if mspec.multimodal:
                caps.append("multimodal")
            cap_str = f" [{'/'.join(caps)}]" if caps else ""
            lines.append(
                f"    - {mid}: context={mspec.context}, "
                f"thinking={thinking}, cost={mspec.cost_tier}{cap_str}{mark}"
            )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content="\n".join(lines),
        tool_call_id="",
        tool_name="model_catalog",
    )


def run_switch_model(
    ctx: Any,
    pool: ModelClientPool | None,
    session_set_override: Callable[[str | None], None] | None,
    audit: Callable[[str, dict, str], None] | None,
    args: dict,
) -> ToolResult:
    """switch_model: 切换会话级 model_override + 审计落盘 + 如实回执.

    行为契约 (design §5.3):
    - resolve 失败 → 如实回执（含候选列表），不改变现状
    - client_params 失败（key 缺失）→ 如实回执含 env var 名，不改变现状
    - 成功 → 写 sess.model_override + 回执 + 审计落盘 self_correction_log.jsonl
    - model="default" → 清除 override 回装配默认（同样审计）
    """
    if pool is None:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                "[工具不可用] 事实: 模型客户端池未装配。"
                "原因: 程序未注入 ModelClientPool；switch_model 工具不可用。"
                "建议: 检查装配（factory.build_engine 应已注入）。"
            ),
            tool_call_id="",
            tool_name="switch_model",
        )

    model_ref = str(args.get("model", "")).strip()
    reason = str(args.get("reason", "")).strip()
    if not model_ref:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 缺少必填参数 'model'（目标模型；'default' 清除覆盖）",
            tool_call_id="",
            tool_name="switch_model",
        )
    if not reason:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[参数错误] 缺少必填参数 'reason'（切换原因；审计必填）",
            tool_call_id="",
            tool_name="switch_model",
        )

    # 当前会话 override（用于审计 from→to 标注）
    current_override = getattr(ctx, "session_model_override", None) if ctx else None
    from_label = current_override if current_override else pool.get_default_model()

    # 特殊语义: model="default" → 清除 override 回装配默认
    if model_ref.lower() == "default":
        if session_set_override is not None:
            try:
                session_set_override(None)
            except Exception as exc:  # noqa: BLE001 — 写入异常如实标注
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[清除失败] 事实: 清除会话覆盖写入异常: {exc}。建议: 检查会话存储可写性。",
                    tool_call_id="",
                    tool_name="switch_model",
                )
        if audit is not None:
            audit(
                "switch_model",
                {
                    "from": from_label,
                    "to": "default",
                    "reason": reason,
                    "result": "success",
                },
                "success",
            )
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"[状态: 成功] 模型已切换: {from_label} → default（原因: {reason}）；"
                f"已清除会话覆盖，下一轮 LLM 调用回装配默认。"
            ),
            tool_call_id="",
            tool_name="switch_model",
        )

    # resolve 模型引用 → (provider_id, model_id)
    try:
        provider_id, model_id = pool.registry.resolve(model_ref)
    except ValueError as exc:
        # 如实回执（resolve 失败不改变现状）
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=(
                f"[状态: 失败] 模型 '{model_ref}' 不可用: {exc}。"
                "请用 model_catalog 查候选后重试。"
            ),
            tool_call_id="",
            tool_name="switch_model",
        )

    # client_params 检查（含 key 缺失 → 如实报错含 env var 名）
    try:
        pool.registry.client_params(provider_id, model_id)
    except ValueError as exc:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[状态: 失败] 模型 {provider_id}/{model_id} 不可用: {exc}",
            tool_call_id="",
            tool_name="switch_model",
        )

    # 预构建 client（提前暴露构造异常；缓存命中走快路径）
    try:
        pool.get_client(f"{provider_id}/{model_id}")
    except ValueError as exc:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[状态: 失败] 模型 {provider_id}/{model_id} 客户端构造失败: {exc}",
            tool_call_id="",
            tool_name="switch_model",
        )

    to_label = f"{provider_id}/{model_id}"
    thinking_supported = pool.registry.supports_thinking(provider_id, model_id)

    # 写会话 override
    if session_set_override is not None:
        try:
            session_set_override(to_label)
        except Exception as exc:  # noqa: BLE001 — 写入异常如实标注
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    f"[状态: 失败] 会话覆盖写入失败: {exc}。"
                    "建议: 检查会话存储可写性（会话 JSON 目录权限）。"
                ),
                tool_call_id="",
                tool_name="switch_model",
            )

    # 审计落盘（who/when/from→to/reason; 复用 corrections.py 现有 _audit 通道）
    if audit is not None:
        audit(
            "switch_model",
            {
                "from": from_label,
                "to": to_label,
                "reason": reason,
                "result": "success",
            },
            "success",
        )

    thinking_note = (
        "思考参数: 发送" if thinking_supported else "思考参数: 不发送（该 provider 不支持）"
    )
    return ToolResult(
        status=ToolResultStatus.SUCCESS,
        content=(
            f"[状态: 成功] 模型已切换: {from_label} → {to_label}（原因: {reason}）；"
            f"{thinking_note}。新模型将在下一轮 LLM 调用生效（覆盖已写入会话存储）。"
        ),
        tool_call_id="",
        tool_name="switch_model",
    )


def write_model_tools_audit(
    audit_dir: Any,
    tool_name: str,
    arguments: dict,
    result_status: str,
) -> None:
    """独立审计落盘（model_catalog/switch_model 直接调用时; corrections 复用 _audit 时不必）。

    复用 corrections._audit 行为: 写 self_correction_log.jsonl, fail-open 不抛穿.
    本函数供不经过 CorrectionToolRegistry 的路径（如独立子代理 / 集成测试）使用.
    """
    import json
    from pathlib import Path

    if audit_dir is None:
        return
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "id": f"COR-{datetime.now(UTC).strftime('%Y%m%d')}",
            "ts": datetime.now(UTC).isoformat(),
            "tool_name": tool_name,
            "arguments": arguments,
            "result_status": result_status,
        }
        with (Path(audit_dir) / "self_correction_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # fail-open
