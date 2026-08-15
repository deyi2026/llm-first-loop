"""M50 (design §5.6): providers.json 热重载实现.

从 factory.py 提取的 refresh_config 扩展逻辑, 便于独立测试 + 复用:
- refresh_provider_registry: 重读 env + data/providers.json → 重建 ProviderRegistry
- 失败语义: 保持旧 registry + 中文回执如实标注 (DFX-REL-08 fail-open)
- install_refresh_executor: 注入 refresh_config 工具的 executor (供 build_engine 复用)

"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm_loop.config import Settings
    from llm_loop.llm.pool import ModelClientPool


def refresh_provider_registry(
    pool: ModelClientPool,
    settings: Settings,
    *,
    re_read_settings: bool = True,
) -> tuple[str, object]:
    """刷新 provider 注册表: 重读 env + data/providers.json → 重建 ProviderRegistry.

    Args:
        pool: ModelClientPool（提供 registry 重写入口 + clear_cache 通道）.
        settings: 当前 Settings（用于 load_registry 优先级链）.
        re_read_settings: 是否重新调用 load_settings()（重读 env）；
            测试场景设为 False 可避免 env vars 缺失异常，生产默认 True.

    Returns:
        (msg, new_registry) 中的 msg 是中文回执（含 N→M 变更描述或失败原因）;
        new_registry 总是返回（即使失败也会回退为 L0 合成）,
        调用方按需决定是否应用 (本函数顺便返回以便测试断言).

    Notes:
        - 失败语义: 加载失败 → 旧 registry 保留, 回执如实标注（fail-open, DFX-REL-08）
        - 成功: 返回 (msg, new_registry), 调用方应 `pool.registry = new_registry` + `pool.clear_cache()`
    """
    from llm_loop.llm.providers import load_registry as _load_registry

    old_provider_count = len(pool.registry.providers)
    old_model_count = sum(len(spec.models) for spec in pool.registry.providers.values())
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
        new_model_count = sum(
            len(spec.models) for spec in new_registry.providers.values()
        )
        if new_registry.degraded:
            msg = (
                f"[重载部分完成] 模型目录已重载, 但 providers.json 加载失败: {new_registry.degraded_reason}。"
                f" provider {old_provider_count}→{new_provider_count}, "
                f"模型 {old_model_count}→{new_model_count}（其中包含回落 L0 合成）。"
            )
        else:
            msg = (
                f"[重载完成] 模型目录已从 {old_provider_count} 个 provider / {old_model_count} 个模型 "
                f"变为 {new_provider_count} 个 provider / {new_model_count} 个模型。"
            )
        return msg, new_registry
    except Exception as exc:  # noqa: BLE001 — 重载失败保持旧 registry（fail-open, DFX-REL-08）
        msg = (
            f"[重载失败] 模型目录重载失败: {type(exc).__name__}: {exc}。"
            f" 当前保持旧注册表 ({old_provider_count} 个 provider / {old_model_count} 个模型)。"
        )
        # 失败: 返回原 registry (调用方不应应用 new_registry)
        return msg, pool.registry


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
        # 取当前 settings (engine 提供)
        settings = getattr(engine, "settings", None)
        if settings is None:
            return (
                "[重载失败] engine.settings 缺失, 无法读取新配置。"
            )
        msg, new_registry = refresh_provider_registry(model_pool, settings)
        # 成功: 应用 new_registry (失败 → new_registry == pool.registry, 写入无副作用)
        model_pool.registry = new_registry
        model_pool.clear_cache()
        return msg

    ctx.refresh_executor = _refresh_executor
