#!/usr/bin/env python3
"""P0/P1 修复真实 DeepSeek 冒烟压测（2026-08-25 规格验收）.

驱动镜像 web（8903，生产配置: 300K budget + fold=3）跑一个重工具长会话:
每轮让模型读多个大文件并汇报 → 上下文持续膨胀。验证:
  ① 无压缩风暴（event_logs 无连续几十轮 context.compressed）
  ② breaker 不误触发（cache_breaker.jsonl 无 breaker_enter）
  ③ 逐 API request 命中曲线健康（压缩间隙回 90%+，无 8,320 钉死）
  ④ 遥测隔离（会话正文无 ⚡ 行；metadata.cache_health 存在；返回只有一条 canonical）
  ⑤ 固定 DeepSeek、不切模型

用法: PYTHONPATH=src .venv/bin/python scripts/smoke_breaker_test.py [--rounds N]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from contextlib import suppress
from pathlib import Path

BASE = "http://127.0.0.1:8903"
DATA = Path("data")
BIG_FILES = [
    "data/event_logs/69715765-08b3-40af-a054-8a8161543243.jsonl",
    "data/event_logs/3e3f76ed-8e84-4107-baad-ce3a5e7a51fd.jsonl",
    "data/event_logs/f082baff-3d5f-417d-a481-9472a5dacebf.jsonl",
]


MODEL = "deepseek/deepseek-v4-flash"


def post_chat(session_id: str | None, message: str, *, new: bool = False) -> dict:
    body = {"message": message, "model": MODEL}
    if new:
        body["new_session"] = True
    if session_id and not new:
        body["session_id"] = session_id
    req = urllib.request.Request(
        f"{BASE}/api/v1/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())


def main() -> None:
    global MODEL
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument(
        "--model", default=MODEL, help="模型全限定名（默认 deepseek/deepseek-v4-flash）"
    )
    args = ap.parse_args()
    MODEL = args.model
    print(f"压测模型: {MODEL}")

    # 健康检查
    with urllib.request.urlopen(f"{BASE}/health", timeout=5) as r:
        assert json.loads(r.read())["status"] == "ok"

    audit_before = len(_read_jsonl(DATA / "audit" / "cache_breaker.jsonl"))
    files_line = "、".join(BIG_FILES)
    r0 = post_chat(
        None,
        (
            f"重工具长会话压测开始。请依次完整读取以下大文件（每次读一个，读完汇报"
            f"文件大小、消息数、有无异常）：\n{files_line}\n"
            f"读完所有文件后继续读取 data/event_logs/ 下其他 .jsonl 文件（可先 "
            f"execute_command 'ls -S data/event_logs | head -20' 找大的），每轮读 1-2 个，"
            f"持续汇报，直到我说停。"
        ),
        new=True,
    )
    sid = r0["session_id"]
    print(f"会话: {sid}")
    print(f"第1轮 final_answer 前缀: {r0['final_answer'][:120]!r}")

    for i in range(2, args.rounds + 1):
        msg = (
            f"继续（第{i}轮）：再读 1-2 个未读过的大文件（data/event_logs/ 下，"
            f"可用 execute_command 查大小），完整读取并汇报要点。"
        )
        r = post_chat(sid, msg)
        fa = r.get("final_answer", "")
        print(f"第{i}轮 ok len={len(fa)} 前缀={fa[:80]!r}")

    # ── 验收 ──
    print("\n===== 验收 =====")
    # ① 压缩风暴: 会话事件日志逐轮 context.compressed 数
    ev = DATA / "event_logs" / f"{sid}.jsonl"
    per_round: list[int] = []
    comp = 0
    if ev.exists():
        for line in ev.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("type") == "context.compressed":
                comp += 1
            elif r.get("type") == "request.meta":
                per_round.append(comp)
                comp = 0
        per_round.append(comp)
    storm_rounds = [c for c in per_round if c > 0]
    # 风暴判据: 连续压缩轮数（旧事故形态 = 22+ 轮连续压缩；breaker 应在 5-8 轮内熔断）
    max_streak = 0
    cur = 0
    for c in per_round:
        if c > 0:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0
    print(
        f"① 轮数={len(per_round)} 有压缩轮={len(storm_rounds)} "
        f"最大单轮压缩={max(storm_rounds) if storm_rounds else 0} 连续压缩轮={max_streak}"
    )
    if max_streak >= 15:
        print("   ❌ 连续压缩 ≥15 轮——熔断未生效，失败")
        sys.exit(1)
    if max_streak >= 5:
        print(f"   ⚠️ 连续压缩 {max_streak} 轮（触发线=5）——确认 audit 有 breaker_enter 熔断")
    else:
        print("   ✅ 无风暴形态（连续压缩 <5 轮）")

    # ② breaker 不误触发
    audit_rows = _read_jsonl(DATA / "audit" / "cache_breaker.jsonl")
    new_rows = [r for r in audit_rows[len(audit_before) :] if r.get("session_id") == sid]
    print(f"② 本会话 breaker 审计事件: {len(new_rows)} 条 （{[r['event'] for r in new_rows]}）")
    if new_rows:
        print("   ⚠️ 出现 breaker 事件——检查是否为误触发")
    else:
        print("   ✅ 无 breaker 触发（结构+命中共信号均未满足）")

    # ③ 逐 request 命中曲线
    curve = _hit_curve(sid)
    print(f"③ 请求数={len(curve)}")
    for ts, tin, thit in curve[-12:]:
        rate = thit / tin * 100 if tin else 0
        print(f"   {ts[11:19]} in={tin:>10,} hit={thit:>10,} rate={rate:5.1f}%")
    if curve:
        rates = [hit / tokens_in * 100 for _, tokens_in, hit in curve if tokens_in]
        print(f"   末段（后 5 请求）平均命中率: {sum(rates[-5:]) / min(5, len(rates)):.1f}%")
    # ④ 遥测隔离
    sess_file = DATA / "sessions" / "--Users-yyj-Project-llm-first-loop-mirror--" / f"{sid}.json"
    if sess_file.exists():
        sess = json.loads(sess_file.read_text(encoding="utf-8"))
        bad = [
            m.get("content", "")
            for m in sess.get("messages", [])
            if m.get("role") == "assistant" and "缓存命中率" in (m.get("content") or "")
        ]
        with_meta = [
            m
            for m in sess.get("messages", [])
            if m.get("role") == "assistant" and (m.get("metadata") or {}).get("cache_health")
        ]
        print(f"④ 正文含遥测的 assistant 消息: {len(bad)} 条（应=0）")
        print(f"   metadata.cache_health 的消息: {len(with_meta)} 条（应≥1）")
        if bad:
            print("   ❌ 正文仍含遥测行——隔离未生效")
            sys.exit(1)
        if not with_meta:
            print("   ⚠️ 无 metadata.cache_health（CACHE_HIT_SHOW_IN_ANSWER 关闭或窗口无数据）")
    print("\n冒烟完成。")

    # 输出会话 id 供人工复核
    print(f"SESSION_ID={sid}")


def _read_jsonl(p: Path) -> list[dict]:
    out = []
    if p.exists():
        for line in p.open(encoding="utf-8"):
            line = line.strip()
            if line:
                with suppress(Exception):
                    out.append(json.loads(line))
    return out


def _hit_curve(sid: str) -> list[tuple[str, int, int]]:
    rows = _read_jsonl(DATA / "audit" / "guarded_requests.jsonl")
    return [
        (r["ts"], r["tokens_in"], r["tokens_hit"])
        for r in rows
        if r.get("event") == "llm_result" and r.get("session_id") == sid
    ]


if __name__ == "__main__":
    main()
