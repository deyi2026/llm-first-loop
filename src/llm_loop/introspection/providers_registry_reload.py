"""M50 (design §5.6): providers.json 热重载实现.

从 factory.py 提取的 refresh_config 扩展逻辑, 便于独立测试 + 复用:
- refresh_provider_registry: 重读 env + data/providers.json → 重建 ProviderRegistry
- 失败语义: 保持旧 registry + 中文回执如实标注 (DFX-REL-08 fail-open)
- install_refresh_executor: 注入 refresh_config 工具的 executor (供 build_engine 复用)

"""

from __future__ import annotations

from typing import Any

from llm_loop.config import Settings
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import ProviderRegistry


def refresh_provider_registry(
    pool: ModelClientPool,
    settings: Settings,
    *,
    re_read_settings: bool = True,
) -> tuple[str, ProviderRegistry]:
    """刷新 provider 注册表: 重读 env + data/providers.json → 重建 ProviderRegistry.

    Args:
        pool: ModelClientPool（提供 replace_registry 原子切表与旧 client 退休通道）.
        settings: 当前 Settings（用于 load_registry 优先级链）.
        re_read_settings: 是否重新调用 load_settings()（重读 env）；
            测试场景设为 False 可避免 env vars 缺失异常，生产默认 True.

    Returns:
        (msg, new_registry) 中的 msg 是中文回执（含 N→M 变更描述或失败原因）;
        new_registry 总是返回（即使失败也会回退为 L0 合成）,
        调用方按需决定是否应用 (本函数顺便返回以便测试断言).

    Notes:
        - 失败语义: 加载失败 → 旧 registry 保留, 回执如实标注（fail-open, DFX-REL-08）
        - 成功: 返回 (msg, new_registry), 调用方应 `pool.replace_registry(new_registry)` 原子切表并退休旧缓存
    """
    from llm_loop.llm.providers import load_registry as _load_registry

    old_registry = pool.registry_snapshot()
    old_provider_count = len(old_registry.providers)
    old_model_count = sum(len(spec.models) for spec in old_registry.providers.values())
    try:
        # 重新读取 env + providers.json（生产路径走 load_registry 优先级链）
        if re_read_settings:
            from llm_loop.config import load_env_file, load_settings

            # EVO-HOTFIX: 热重载前先重读 .env 文件——
            # 根因: load_settings() 只读 os.environ，启动后写入 .env 的新配置
            # （如 MINIMAX_API_KEY）永远进不了进程 → 热重载形同空转。
            # load_env_file 环境优先（不覆盖已存在值）、文件缺失 fail-open，安全。
            load_env_file()
            new_settings = load_settings()
        else:
            new_settings = settings
        new_registry = _load_registry(new_settings)
        new_provider_count = len(new_registry.providers)
        new_model_count = sum(len(spec.models) for spec in new_registry.providers.values())
        if new_registry.degraded:
            msg = (
                f"[重载部分完成] 模型目录已重载, 但 providers.json 加载失败: {new_registry.degraded_reason}。"
                f" provider {old_provider_count}→{new_provider_count}, "
                f"模型 {old_model_count}→{new_model_count}（其中包含回落 L0 合成）。"
            )
        else:
            # Provider-level history budget participates in routed-model budget
            # calculation through the exact registry snapshot. Refreshed override/
            # fallback routes see it immediately; the shared default route remains
            # intentionally bound to its startup registry snapshot until restart.
            budget_changes = []
            for pid in set(old_registry.providers) | set(new_registry.providers):
                old_spec = old_registry.providers.get(pid)
                new_spec = new_registry.providers.get(pid)
                old_b = getattr(old_spec, "history_budget_chars", None) if old_spec else None
                new_b = getattr(new_spec, "history_budget_chars", None) if new_spec else None
                if old_b != new_b:
                    budget_changes.append(f"{pid}: {old_b}→{new_b}")
            budget_note = ""
            if budget_changes:
                budget_note = (
                    " ⚠️ 其中 provider 级 history_budget_chars 有变更（"
                    + "、".join(budget_changes)
                    + "）；新 override/fallback 路由按新 registry 即时计算，"
                    "默认路由仍绑定启动快照，需重启后才使用新值。"
                )
            msg = (
                f"[重载完成] 模型目录已从 {old_provider_count} 个 provider / {old_model_count} 个模型 "
                f"变为 {new_provider_count} 个 provider / {new_model_count} 个模型。"
                f"{budget_note}"
            )
        return msg, new_registry
    except Exception as exc:  # noqa: BLE001 — 重载失败保持旧 registry（fail-open, DFX-REL-08）
        msg = (
            f"[重载失败] 模型目录重载失败: {type(exc).__name__}: {exc}。"
            f" 当前保持旧注册表 ({old_provider_count} 个 provider / {old_model_count} 个模型)。"
        )
        # 失败: 返回原 registry (调用方不应应用 new_registry)
        return msg, old_registry


def install_refresh_executor(engine: object) -> None:
    """M50: 注入 refresh_config 工具的 executor 到 correction_ctx.

    复用 factory 装配: 将 refresh_executor 替换为 providers.json 热重载版本.
    若 engine 无 correction_ctx / model_pool, 静默跳过（注入失败不抛）.
    """
    ctx = getattr(engine, "correction_ctx", None)
    model_pool = getattr(ctx, "model_pool", None) if ctx is not None else None
    if ctx is None or model_pool is None:
        return

    def _refresh_executor() -> str:
        # EVO-20260815-b3339561 Phase 1（2026-08-15）:
        # 原缺口: 回执声明"重载完成"但 default_client 持启动时旧凭据（MINIMAX_API_KEY
        # 写入 .env 后重载，新 provider 生效而默认路由仍用旧 key）——声明未真实生效。
        # 当前语义: provider registry 热重载即时生效；共享 default_client 只检测差异并要求重启，
        # 避免并发原地改写与底层 transport 配置不一致。
        from llm_loop.config import load_env_file, load_settings

        try:
            load_env_file()  # 环境优先（不覆盖已存在值）、文件缺失 fail-open
            new_settings = load_settings()
        except Exception as exc:  # noqa: BLE001 — env/settings 读取失败如实回执，不动 registry
            return (
                f"[重载失败] 配置读取失败: {type(exc).__name__}: {exc}。当前保持旧注册表与旧凭据。"
            )

        snapshot_fn = getattr(model_pool, "registry_snapshot", None)
        old_registry = snapshot_fn() if callable(snapshot_fn) else model_pool.registry
        msg, new_registry = refresh_provider_registry(
            model_pool, new_settings, re_read_settings=False
        )
        # 失败时 helper 返回原 registry：不摘缓存、不制造无意义退休。
        summary_note = ""
        if new_registry is not old_registry:
            model_pool.replace_registry(new_registry)

            # 独立 SUMMARY_MODEL client 是长期对象，不能在切表后永久持旧 endpoint/key。
            # 这里只重绑定“本进程启动时已选择的 summary_model”；如果新 Settings 改了
            # SUMMARY_MODEL 本身，仍按下方 restart 语义处理，不在运行中偷偷切模型。
            runtime_settings = getattr(engine, "settings", None)
            summary_model = getattr(runtime_settings, "summary_model", "") or ""
            if not isinstance(summary_model, str):
                summary_model = ""
            summarizers: list[Any] = []
            for candidate in (
                getattr(engine, "summarizer", None),
                getattr(ctx, "summarizer", None),
            ):
                if candidate is not None and all(candidate is not item for item in summarizers):
                    summarizers.append(candidate)
            if summary_model and summarizers:
                try:
                    summary_client = model_pool.get_client(summary_model)
                except Exception as exc:  # noqa: BLE001 — 摘要失败应降级，不保留旧凭据/client
                    for summarizer in summarizers:
                        summarizer.llm = None
                    summary_note = (
                        f" 独立摘要模型 {summary_model} 在新注册表中不可用"
                        f"（{type(exc).__name__}），已释放旧 client 并降级为确定性摘要。"
                    )
                else:
                    for summarizer in summarizers:
                        summarizer.llm = summary_client
                    summary_note = f" 独立摘要模型 {summary_model} client 已切换到新注册表。"

        # default_client 同时被 engine/extractor/summarizer 等长期共享。逐字段原地热改会让
        # 并发请求观察到半新半旧配置，且底层 httpx transport 仍是启动时配置。
        # 因此这里只检测差异并如实要求重启；provider override 目录已通过上面的原子切表生效。
        default_client = getattr(model_pool, "default_client", None)
        changed: list[str] = []
        if default_client is not None:
            for attr, new_val in (
                ("api_key", new_settings.llm_api_key),
                ("base_url", new_settings.llm_base_url),
                ("model", new_settings.llm_model),
                ("wire_protocol", new_settings.llm_wire_protocol),
            ):
                if new_val and getattr(default_client, attr, None) != new_val:
                    changed.append(attr)

        default_contract_note = (
            "默认路由完整 provider/model contract 绑定启动快照；即使仅 providers.json "
            "中的 context/max_tokens/reasoning/tool-choice 等元数据变化，也需重启后作用于默认路由。"
        )
        if changed:
            hot_note = (
                "⚠️ 默认 client 配置检测到变更（字段: "
                + ", ".join(changed)
                + "）；为保证在途请求与底层连接配置一致，本次未原地热改，需重启进程生效。"
            )
        else:
            hot_note = "默认 client 的 env 基础字段已核验与新配置一致。"
        restart_note = (
            "其余 Settings 字段为启动时装配（冻结），变更需重启进程生效；"
            "运行参数（max_iterations/timeout_s/history_budget）请用 adjust_strategy 即时调整。"
        )
        return f"{msg} {hot_note}{default_contract_note}{summary_note}{restart_note}"

    ctx.refresh_executor = _refresh_executor
