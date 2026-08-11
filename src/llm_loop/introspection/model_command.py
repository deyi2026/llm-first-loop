"""M50：三端模型切换 `/model` 指令统一处理（CLI / 飞书 共用）.

设计要点（design §5.6 + §六）:
- 三端 `/model` 指令复用同一套处理逻辑, 同一份 session override 存储
- 三形态契约:
  - `/model` (无参) → 列出当前会话模型 + 目录
  - `/model <ref>` → 切换 (provider/model 或裸模型名)
  - `/model default` → 清除 override 回装配默认
- 切换成功/失败回执通过格式统一构造, 三端复用文案
- 密钥安全 (DFX-SEC-02): 回执不暴露 api_key / base_url 之外的敏感信息

参考: docs/model_switch_config_design.md §5.6 / §六
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from llm_loop.core.session import Session, SessionStore
from llm_loop.introspection.corrections import CorrectionContext
from llm_loop.introspection.tools_model import run_model_catalog, run_switch_model

# ── 指令识别 ──


MODEL_CMD_TRIGGERS: tuple[str, ...] = ("/model", "/Model", "/MODEL")
"""触发识别的指令前缀（与 CLI/飞书命令风格对齐）."""


def parse_model_command(text: str) -> tuple[bool, str]:
    """解析消息是否为 `/model` 指令.

    Args:
        text: 原始消息文本（已 strip）.

    Returns:
        (is_model_cmd, arg) — arg 为 `/model` 后面的参数（已 strip; 无参数时为空字符串）.
        非指令时 is_model_cmd=False, arg=原文本.
    """
    stripped = text.strip()
    for prefix in MODEL_CMD_TRIGGERS:
        if stripped == prefix:
            return True, ""
        if stripped.startswith(prefix + " "):
            arg = stripped[len(prefix) + 1:].strip()
            return True, arg
    return False, text


# ── 三形态处理 ──


@dataclass(frozen=True)
class ModelCommandResult:
    """`/model` 指令处理结果（统一文案，三端复用）."""

    success: bool
    reply: str  # 用户可见的回复文本
    changed: bool = False  # 是否实际修改了 session override（影响是否需要持久化）


def _list_reply(ctx: CorrectionContext, session: Session | None) -> str:
    """`/model` 无参 → 列出当前会话模型 + 目录（M48 model_catalog 复用）.

    Args:
        ctx: CorrectionContext（持有 model_pool）
        session: 当前会话（用于读取 override; None 时跳过当前会话覆盖）
    """
    if ctx.model_pool is None:
        return (
            "[模型目录不可用] 事实: 模型客户端池未装配（model_pool=None）。"
            "原因: 程序未注入 ModelClientPool。建议: 检查 engine 装配。"
        )
    override = session.model_override if session is not None else None
    result = run_model_catalog(ctx, ctx.model_pool, override)
    return result.content


def _list_reply_success(ctx: CorrectionContext, session: Session | None) -> bool:
    """列表形态是否成功（model_pool 不存在时为 False）。"""
    return ctx.model_pool is not None


def _switch_reply(
    ctx: CorrectionContext,
    session: Session | None,
    session_store: SessionStore,
    model_ref: str,
    audit: Callable[[str, dict, str], None] | None,
) -> ModelCommandResult:
    """`/model <ref>` 切换 → 复用 M48 run_switch_model + 写会话 override + 持久化.

    Args:
        ctx: CorrectionContext（持有 model_pool + session_set_override）.
        session: 当前会话（in-memory 引用; None 时不修改本身, 仅审计回执）.
        session_store: SessionStore（changed=True 时持久化）.
        model_ref: 目标模型引用（'provider/model' / 裸名 / 'default'）.
        audit: 审计回调（corrections._audit 闭包; None 时不审计）.

    设计要点:
    - session_set_override: LoopEngine.run() 路径会注入回调; CLI/飞书 路径 ctx.session_set_override 可能为 None,
      本函数提供 fallback: 直接修改 in-memory sess.model_override 字段 + 修正 ctx.session_model_override.
    """
    if ctx.model_pool is None:
        return ModelCommandResult(
            success=False,
            reply=(
                "[切换不可用] 事实: 模型客户端池未装配（model_pool=None）。"
                "原因: 程序未注入 ModelClientPool。建议: 检查 engine 装配。"
            ),
        )

    # fallback override 写入: ctx.session_set_override 为 None 时直接改 in-memory session
    # 关键: 每次调用 freshness 闭环 (闭包捕获本回调的 session, 避免与上一个调用冲突)
    if session is not None:
        def _fallback_set_override(value: str | None, _sess: Session = session) -> None:
            _sess.model_override = value
            ctx.session_model_override = value

        # 始终覆写：避免被上一次调用捕住的旧 session 覆盖本次新 session
        ctx.session_set_override = _fallback_set_override

    # 复用 M48 run_switch_model (审计 + resolve + client_params 校验 + 写 override + 回执)
    result = run_switch_model(
        ctx,
        ctx.model_pool,
        ctx.session_set_override,
        audit,
        {"model": model_ref, "reason": "M50 CLI/飞书 /model 指令切换"},
    )
    success = result.status.value == "success"
    # changed 语义: 成功且回执包含"已切换/已清除"标记
    changed = success and session is not None and (
        "已切换" in result.content or "已清除" in result.content
    )
    # 持久化（run_switch_model 内部已调用 session_set_override 修改 in-memory sess；
    #  CLI/飞书 路径不经过 LoopEngine.run() → 需手动 save 以落到 JSON）
    if changed and session is not None:
        try:
            session_store.save(session)
        except Exception as exc:  # noqa: BLE001 — 持久化失败如实标注
            return ModelCommandResult(
                success=False,
                reply=(
                    f"[状态: 失败] 模型切换失败：持久化异常（{type(exc).__name__}: {exc}）。"
                    "会话已 in-memory 生效但未落盘，重启后失效。"
                ),
                changed=False,
            )
    return ModelCommandResult(success=success, reply=result.content, changed=changed)


def handle_model_command(
    text: str,
    ctx: CorrectionContext,
    session: Session | None,
    session_store: SessionStore,
    audit: Callable[[str, dict, str], None] | None = None,
) -> ModelCommandResult | None:
    """统一 `/model` 指令处理入口（CLI / 飞书 共用）.

    Args:
        text: 原始消息文本.
        ctx: CorrectionContext（model_pool + session_set_override）.
        session: 当前会话（in-memory Session 实例; 无会话时传 None）.
        session_store: SessionStore（持久化用）.
        audit: 审计回调（corrections._audit 闭包; None 时不审计）.

    Returns:
        ModelCommandResult | None — None 表示非 `/model` 指令, 调用方应继续走正常流程.
        否则返回处理结果 + reply 文案, 调用方直接展示.

    设计原则（design §三 原则 2 如实反馈）:
    - 切换成功/失败/降级全部构造 `[状态: xxx]` 回执
    - 失败路径不静默降级
    - 密钥不出域（不回显 api_key / base_url）
    """
    is_cmd, arg = parse_model_command(text)
    if not is_cmd:
        return None

    # 形态 1: /model (无参) → 列出目录
    if not arg:
        reply = _list_reply(ctx, session)
        return ModelCommandResult(success=_list_reply_success(ctx, session), reply=reply)

    # 形态 2/3: /model <ref> 或 /model default
    return _switch_reply(ctx, session, session_store, arg, audit)


def format_cli_reply(result: ModelCommandResult) -> str:
    """CLI 端输出格式（飞书/Web 端可复用同原文）.

    CLI 端直接打印 reply 全文即可; 飞书端可能因 chunk 过长回执被分级;
    Web 端暂未对接（保留扩展位）。
    """
    return result.reply
