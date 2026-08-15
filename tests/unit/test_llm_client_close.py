"""P2-4(2026-08-15) LLMClient.close() 接线测试（httpx 连接释放）.

覆盖:
- ModelClientPool.close(): 关闭 default_client + 全部缓存 client，幂等，fail-open
- ModelClientPool.clear_cache(): 关闭旧缓存 client 后再清空（default 不关）
- LoopEngine.close(): pool / 无 pool 两种装配下都幂等不抛，fail-open
- CLI main()/_dispatch_command try-finally 接线（engine.close 必被调用）
- 飞书 _close_engine 停机路径（handler._engine 可达 + duck-typing 防御）
"""

from __future__ import annotations

import types
from unittest import mock

from llm_loop.core.loop import LoopEngine
from llm_loop.llm.pool import ModelClientPool


class _CloseTracker:
    """可编程 close 追踪桩（可注入关闭异常验证 fail-open）."""

    def __init__(self, raise_on_close: bool = False) -> None:
        self.close_calls = 0
        self.raise_on_close = raise_on_close

    def close(self) -> None:
        self.close_calls += 1
        if self.raise_on_close:
            raise RuntimeError("close 失败（测试注入）")


class _NoCloseClient:
    """无 close 方法的 client（duck-typing 防御路径）."""


def _make_pool(default=None, cached: dict | None = None) -> ModelClientPool:
    """构造 pool（default_client/cache 用 _CloseTracker，不触网）."""
    pool = ModelClientPool(
        registry=object(),  # type: ignore[arg-type] — 测试仅用缓存直插，不走路由
        default_client=default if default is not None else _CloseTracker(),  # type: ignore[arg-type]
    )
    if cached:
        pool._provider_cache.update(cached)  # noqa: SLF001 — 测试直插缓存（conftest 同款）
    return pool


def _make_engine(llm, llm_pool) -> LoopEngine:
    """最小装配 LoopEngine（仅验证 close 接线，不走 run）."""
    return LoopEngine(
        llm_client=llm,  # type: ignore[arg-type]
        registry=object(),  # type: ignore[arg-type]
        memory=object(),  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        settings=object(),  # type: ignore[arg-type]
        llm_pool=llm_pool,  # type: ignore[arg-type]
    )


# ── ModelClientPool.close ──


def test_pool_close_closes_default_and_cached():
    default = _CloseTracker()
    cached_a = _CloseTracker()
    cached_b = _CloseTracker()
    pool = _make_pool(default=default, cached={"a": cached_a, "b": cached_b})

    pool.close()

    assert default.close_calls == 1
    assert cached_a.close_calls == 1
    assert cached_b.close_calls == 1
    assert pool.cached_provider_ids() == []  # 关闭后缓存清空


def test_pool_close_idempotent():
    default = _CloseTracker()
    cached = _CloseTracker()
    pool = _make_pool(default=default, cached={"a": cached})

    pool.close()
    pool.close()  # 第二次调用不抛（幂等）；缓存已清空仅 default 再次关闭

    assert default.close_calls == 2
    assert cached.close_calls == 1


def test_pool_close_fail_open():
    default = _CloseTracker()
    bad = _CloseTracker(raise_on_close=True)
    ok = _CloseTracker()
    pool = _make_pool(default=default, cached={"bad": bad, "ok": ok})

    pool.close()  # bad 关闭失败 → warning 继续，不抛

    assert default.close_calls == 1
    assert bad.close_calls == 1  # 尝试过
    assert ok.close_calls == 1  # 后续 client 仍被关闭
    assert pool.cached_provider_ids() == []  # 缓存仍被清空


def test_pool_close_missing_close_method():
    """无 close 方法的 client（duck-typing 防御）→ 跳过不抛."""
    default = _CloseTracker()
    pool = _make_pool(default=default, cached={"x": _NoCloseClient()})

    pool.close()

    assert default.close_calls == 1
    assert pool.cached_provider_ids() == []


# ── ModelClientPool.clear_cache（P2-4 语义更新）──


def test_pool_clear_cache_closes_old_clients_keeps_default():
    default = _CloseTracker()
    cached = _CloseTracker()
    pool = _make_pool(default=default, cached={"a": cached})

    pool.clear_cache()

    assert cached.close_calls == 1  # 旧缓存 client 已关闭
    assert default.close_calls == 0  # default 不归 cache 管，保持打开
    assert pool.cached_provider_ids() == []


def test_pool_clear_cache_idempotent():
    cached = _CloseTracker()
    pool = _make_pool(cached={"a": cached})

    pool.clear_cache()
    pool.clear_cache()  # 第二次清空（缓存已空）不抛

    assert cached.close_calls == 1


def test_pool_clear_cache_fail_open():
    bad = _CloseTracker(raise_on_close=True)
    ok = _CloseTracker()
    pool = _make_pool(cached={"bad": bad, "ok": ok})

    pool.clear_cache()  # bad 关闭失败 → warning 继续

    assert ok.close_calls == 1
    assert pool.cached_provider_ids() == []


# ── LoopEngine.close ──


def test_engine_close_with_pool():
    llm = _CloseTracker()
    pool = _CloseTracker()
    engine = _make_engine(llm, pool)

    engine.close()
    engine.close()  # 幂等

    assert pool.close_calls == 2
    assert llm.close_calls == 0  # pool 非 None → 不直接关 llm（由 pool 统一管）


def test_engine_close_without_pool():
    llm = _CloseTracker()
    engine = _make_engine(llm, None)

    engine.close()
    engine.close()  # 幂等

    assert llm.close_calls == 2


def test_engine_close_fail_open():
    llm = _CloseTracker()
    pool = _CloseTracker(raise_on_close=True)
    engine = _make_engine(llm, pool)

    engine.close()  # pool.close 抛 → fail-open 不抛穿

    assert pool.close_calls == 1


def test_engine_close_missing_close_method():
    engine = _make_engine(_NoCloseClient(), None)

    engine.close()  # 无 close → 跳过不抛


def test_engine_close_missing_pool_close_falls_to_llm():
    """pool 非 None 但无 close → 按 getattr 防御跳过 pool，不误伤（不抛）."""
    llm = _CloseTracker()
    engine = _make_engine(llm, _NoCloseClient())

    engine.close()

    assert llm.close_calls == 0  # pool 非 None 分支只尝试 pool.close


# ── CLI 接线（main / _dispatch_command try-finally）──


def test_cli_main_finally_closes_engine(monkeypatch):
    """P2-4: cli.main() 单条/交互两条返回路径都在 finally 关闭 engine."""
    import llm_loop.cli as cli_mod

    closed: list[int] = []

    class _FakeEngine:
        def __init__(self) -> None:
            self.registry = mock.MagicMock()

        def close(self) -> None:
            closed.append(1)

    monkeypatch.setattr("llm_loop.config.load_env_file", lambda: None)
    monkeypatch.setattr("llm_loop.introspection.proc_version.record_process_start", lambda *a, **k: None)
    # load_settings 在 cli 模块顶层按值导入 → 需 patch llm_loop.cli.load_settings
    monkeypatch.setattr(cli_mod, "load_settings", lambda: object())
    monkeypatch.setattr("llm_loop.factory.build_engine", lambda settings: _FakeEngine())
    monkeypatch.setattr(cli_mod, "_run_single", lambda engine, text, session_id=None: None)
    monkeypatch.setattr(cli_mod, "_run_interactive", lambda engine, session_id=None: None)

    assert cli_mod.main(["hello"]) == 0
    assert closed == [1]

    closed.clear()
    assert cli_mod.main(["--interactive"]) == 0
    assert closed == [1]


def test_cli_dispatch_finally_closes_engine(monkeypatch):
    """P2-4: _dispatch_command 子命令分派退出前统一关闭 engine（覆盖全部 return 出口）."""
    import llm_loop.cli as cli_mod

    closed: list[int] = []

    class _FakeEngine:
        def close(self) -> None:
            closed.append(1)

    monkeypatch.setattr(cli_mod, "load_settings", lambda: object())
    monkeypatch.setattr("llm_loop.factory.build_engine", lambda settings: _FakeEngine())
    monkeypatch.setattr(cli_mod, "_cmd_list", lambda engine, *a, **k: 0)

    assert cli_mod._dispatch_command(["list"]) == 0
    assert closed == [1]

    # 未知子命令（return 2 出口）同样关闭
    closed.clear()
    assert cli_mod._dispatch_command(["no-such-cmd"]) == 2
    assert closed == [1]


# ── 飞书停机路径接线（_close_engine）──


def test_feishu_close_engine_via_handler():
    """P2-4: 飞书 _close_engine 经 handler._engine 关闭引擎（幂等）."""
    from llm_loop.feishu import _close_engine

    engine = _CloseTracker()
    _close_engine(types.SimpleNamespace(_engine=engine))
    _close_engine(types.SimpleNamespace(_engine=engine))

    assert engine.close_calls == 2


def test_feishu_close_engine_missing_engine_or_close():
    """P2-4: engine 缺失 / 无 close → duck-typing 防御跳过不抛."""
    from llm_loop.feishu import _close_engine

    _close_engine(types.SimpleNamespace())  # 无 _engine
    _close_engine(types.SimpleNamespace(_engine=_NoCloseClient()))  # 无 close


def test_feishu_close_engine_fail_open():
    """P2-4: 引擎 close 异常 → warning 不抛穿（fail-open）."""
    from llm_loop.feishu import _close_engine

    _close_engine(types.SimpleNamespace(_engine=_CloseTracker(raise_on_close=True)))
