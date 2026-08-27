#!/usr/bin/env python3
"""err1210 P0 冒烟验证（tasks 4.4，手工执行不入 CI）.

驱动真实 LoopEngine.run 走完 P0 全路径，肉眼核对四点（tasks 4.4 原文）:
1. 剥离副本前缀一致（retry == orig 去尾部注入，逐字节）
2. 重试恰好 1 次
3. defer 槽位回填（gate_note 复位 + 下一轮 build 重注入）
4. exception_log 仍保留原始 1210 失败记录（不掩盖信号）

附加核对: offending_payloads 快照落盘（无凭据）、defer_trace 审计事件。
零真实网络（_FakeLLMClient duck-typing，engine.py:720 同步兼容点），
工厂复用 tests/unit/test_model_attribution.py（单一真相，不复制装配代码）。

用法: .venv/bin/python scripts/smoke_err1210.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "unit"))

ZHIPU_PROVIDERS = json.dumps(
    {
        "zhipu": {
            "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
            "api_key_env": "ZHIPU_API_KEY",
            "models": {"glm-5": {"context": 1000000, "thinking": True, "cost_tier": "high"}},
            "default_model": "glm-5",
        }
    },
    ensure_ascii=False,
)

_ERR_BODY = '{"error":{"code":"1210","message":"API 调用参数有误，请检查文档。"}}'


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="smoke_err1210_")
    data_dir = Path(tmp) / "data"
    os.environ.update(
        {
            "LFL_DATA_DIR": str(data_dir),  # defer_trace 落点（err1210.py:121）
            "ZHIPU_API_KEY": "smoke-key",
            "ERR1210_RECOVERY": "1",
            "ERR1210_SNAPSHOT": "1",
            "ERR1210_DEFER_TRACE": "1",
        }
    )
    import test_model_attribution as ta
    from llm_loop.core.cache_health import GATE_NOTE_CONTENT
    from llm_loop.llm.client import LLMResponse
    from llm_loop.llm.errors import LLMHTTPError

    settings = ta._settings(
        Path(tmp),
        model_providers_raw=ZHIPU_PROVIDERS,
        llm_model="zhipu/glm-5",
        history_max_chars=300_000,
        self_inspection_enabled=True,  # exception_log 落盘门禁（status.py:187）
    )
    fake = ta._FakeLLMClient("zhipu/glm-5")
    fake.queue(
        [
            LLMHTTPError(f"HTTP 400: Bad Request | {_ERR_BODY}", status_code=400, body=_ERR_BODY),  # 对齐 client.py:1362 _raise_for_status 生产构造（message 拼 body，spec 6.1）
            LLMResponse(content="冒烟恢复后的正常回答", tool_calls=[], provider="fake"),
        ]
    )
    pool = ta._make_pool(settings, fake, cached={"zhipu": fake})
    engine = ta._make_engine(Path(tmp), pool, settings)

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

    # ── 场景 1: P0 恢复主路径 ──
    sid = engine.session.create()
    engine._last_request_msg_count_by_session[sid] = 100  # 骤降兜底武装（prev=100 vs 实际 ~10）
    engine._cache_monitor._get_bucket(sid).gate_note_pending = True  # 尾部注入槽武装
    print(f"[场景1] P0 恢复主路径（会话 {sid[:8]}，compact 首请求 + 1210 + gate_note 注入）")
    result = engine.run(sid, "冒烟任务")

    orig, retry = fake.calls[0]["messages"], fake.calls[1]["messages"]
    n_inj = len(engine._last_build_injections)
    check("重试恰好 1 次", len(fake.calls) == 2, f"calls={len(fake.calls)}")
    check("恢复轮 resp 正常合流", "冒烟恢复后的正常回答" in (result.final_answer or ""))
    check(
        "剥离前缀逐字节一致",
        retry == orig[: len(orig) - n_inj],
        f"n_inj={n_inj}, orig={len(orig)} → retry={len(retry)}",
    )
    check(
        "重试请求尾部无注入",
        not any(
            str(m.get("content", "")).startswith(("[上下文注入", "[门禁干预"))
            for m in retry[-3:]
        ),
    )
    check("defer 槽位回填（gate_note 复位）", engine._cache_monitor._get_bucket(sid).gate_note_pending is True)  # 非消费式核对（take 会消费，留给场景 2 重注入）

    # ── 场景 2: defer 重注入下一轮 ──
    print("[场景2] defer 重注入（下一轮 build，旧消息先注入 spec 5.1.3-3）")
    fake.queue([LLMResponse(content="第二轮正常回答", tool_calls=[], provider="fake")])
    engine.run(sid, "第二轮任务")
    third = fake.calls[2]["messages"]
    check("gate_note 内容下一轮再现", any(m.get("content") == GATE_NOTE_CONTENT for m in third))
    check("重注入轮一次性消费语义正常", engine._cache_monitor.take_gate_note(sid) is False)

    # ── 审计产物核对 ──
    print("[审计产物]")
    audit = data_dir / "audit"
    exc_log = audit / "exception_log.jsonl"
    ok = exc_log.exists() and "1210" in exc_log.read_text(encoding="utf-8")
    check("exception_log 保留原始 1210 记录", ok, str(exc_log))
    snaps = list((audit / "offending_payloads").glob("*.json"))
    cred_ok = all("api_key" not in s.read_text(encoding="utf-8").lower() for s in snaps)
    check("offending_payloads 快照落盘且无凭据", bool(snaps) and cred_ok, f"{len(snaps)} 个快照")
    defer_log = audit / "defer_trace.jsonl"
    events = (
        [json.loads(ln) for ln in defer_log.read_text(encoding="utf-8").splitlines()]
        if defer_log.exists()
        else []
    )
    kinds = {e.get("event") for e in events}
    check(
        "defer_trace 含 stored+replayed 事件",
        {"defer_stored", "defer_replayed"} <= kinds,
        f"events={sorted(str(k) for k in kinds)}",
    )

    n_fail = sum(1 for _, ok_, _ in checks if not ok_)
    print(
        f"\n冒烟结果: {len(checks) - n_fail}/{len(checks)} PASS"
        + (f"，{n_fail} FAIL" if n_fail else " — 全部通过")
    )
    print(f"临时目录: {tmp}（保留不清理，便于肉眼复核审计文件）")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
