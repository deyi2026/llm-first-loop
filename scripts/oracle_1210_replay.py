#!/usr/bin/env python3
"""err1210 P2 双轨 oracle 人工触发命令行（tasks 7.1；design 模块 D / 2.2.2-⑧）.

用法:
  python scripts/oracle_1210_replay.py --snapshot <快照路径> [--track both] \\
      [--budget 20] [--qps 0.5] [--dry-run]

参数:
  --snapshot <path>      模块 C 快照 JSON（data/audit/offending_payloads/ 产出）
  --track both|skeleton|bisect   执行轨道（默认 both = 两轨必跑；单轨不产 Verdict，
                         遵守 R3 禁止项——禁止仅骨架轨下结论，spec 5.2.1-5）
  --budget N             每样本预算（默认取 env ORACLE_1210_BUDGET，缺省 20）
  --qps X                限流（默认取 env ORACLE_1210_QPS，缺省 0.5）
  --dry-run              只构造变体 + 本地 mock 预检，不发送（零生产流量）
  --data-dir <dir>       oracle 报告落盘根（默认 env LFL_DATA_DIR 或 "data"）
  --ticket-ref/--ticket-note   [spec 5.2.1-5b 例外条款] R5 工单官方确认结构性
                          限制时提供：跳过骨架轨，Verdict 由"保真轨数据 + 官方
                          证据源"等效两轨构成（tasks 8.2 收敛分支用）

约束: 生产重放属任务组 8 的人工触发动作——本 CLI 仅提供入口，默认 --dry-run
之外的一切发送由执行者显式确认（spec 5.2.1-3 限流/预算由库侧强制）。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from llm_loop.eval.oracle_1210 import (  # noqa: E402 — 路径引导后导入
    build_variants,
    load_snapshot,
    run_oracle,
)


def _env_default_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        print(f"警告: env {name}={raw!r} 非整数，回退默认 {default}", file=sys.stderr)
        return default


def _env_default_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        print(f"警告: env {name}={raw!r} 非数字，回退默认 {default}", file=sys.stderr)
        return default


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="oracle_1210_replay",
        description="err1210 双轨 oracle 重放（P2 人工触发入口）",
    )
    p.add_argument("--snapshot", required=True, help="模块 C 快照 JSON 路径")
    p.add_argument("--track", choices=("both", "skeleton", "bisect"), default="both")
    p.add_argument(
        "--budget",
        type=int,
        default=_env_default_int("ORACLE_1210_BUDGET", 20),
        help="每样本预算（默认 env ORACLE_1210_BUDGET=20）",
    )
    p.add_argument(
        "--qps",
        type=float,
        default=_env_default_float("ORACLE_1210_QPS", 0.5),
        help="限流 QPS（默认 env ORACLE_1210_QPS=0.5）",
    )
    p.add_argument("--dry-run", action="store_true", help="只产出变体不发送")
    p.add_argument(
        "--data-dir",
        default=os.environ.get("LFL_DATA_DIR", "data"),
        help="报告落盘根目录（默认 env LFL_DATA_DIR 或 data）",
    )
    p.add_argument("--ticket-ref", default="", help="[5.2.1-5b] R5 工单编号")
    p.add_argument("--ticket-note", default="", help="[5.2.1-5b] 工单答复摘要")
    return p.parse_args(argv)


def _client_factory(model: str):
    """生产 client 工厂（env 装配; 仅 live 模式被 run_oracle 调用）.

    样本模型按 MODEL_PROVIDERS 注册表路由；未配置/解析失败回退默认 client
    （LLM_API_KEY/LLM_BASE_URL/LLM_MODEL），并如实警告。
    """

    def factory():
        from llm_loop.config import load_settings
        from llm_loop.llm.client import LLMClient
        from llm_loop.llm.pool import ModelClientPool
        from llm_loop.llm.providers import load_registry

        settings = load_settings()
        default = LLMClient(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_s=settings.llm_timeout_s,
            max_tokens=settings.llm_max_tokens,
            wire_protocol=settings.llm_wire_protocol,
        )
        pool = ModelClientPool(
            registry=load_registry(settings), default_client=default
        )
        if model:
            try:
                return pool.get_client(model)
            except Exception as exc:  # noqa: BLE001 — 路由失败回退默认并警告
                print(f"警告: 样本模型 {model!r} 路由失败（{exc}），回退默认 client", file=sys.stderr)
        return default

    return factory


def _summary(args: argparse.Namespace, report) -> str:
    lines = [
        "err1210 双轨 oracle 重放",
        f"  样本: {args.snapshot}",
        f"  会话: {report.session_id}  模型: {report.model or '（未知）'}",
        f"  轨道: {args.track}  预算: {report.budget}  限流 QPS≤{args.qps}  实测 QPS: {report.qps_actual}",
        f"  dry-run: {'是' if report.dry_run else '否'}",
    ]
    if args.ticket_ref:
        lines.append(
            f"  工单证据: #{args.ticket_ref}（spec 5.2.1-5b 例外条款，跳过骨架轨）"
        )
    if report.variants:
        lines.append("  ── 变体明细 ──")
        for v in report.variants:
            lines.append(
                f"    {v.get('variant_id'):<18} [{v.get('track'):>7}] "
                f"{v.get('outcome'):<16} {str(v.get('detail') or '')[:90]}"
            )
    if report.dry_run:
        lines.append(
            f"  dry-run 完成: 构造 {len(report.variants)} 变体并预检，未发送任何请求"
        )
    else:
        lines.append(
            f"  Verdict: {report.verdict or '（未判定——单轨/不完整不下结论）'}  "
            f"置信度: {report.confidence}"
        )
        if report.minimal_set is not None:
            lines.append(f"  最小消息集（msg_idx）: {report.minimal_set}")
        lines.append(
            f"  预算消耗: {report.budget_used}/{report.budget}  "
            f"完整性: {report.incomplete_reason or '完整'}"
        )
        if report.report_dir:
            lines.append(f"  报告: {report.report_dir}/report.json + report.md")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        sample = load_snapshot(args.snapshot)
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    print(
        f"加载样本: session={sample.session_id} model={sample.model} "
        f"消息数={len(sample.messages)} 注入群={len(sample.span_idx)} 条"
    )
    if not args.dry_run and not args.ticket_ref:
        print(
            f"注意: 生产重放将真实发送请求（预算≤{args.budget}、QPS≤{args.qps}）——"
            "确认后继续（任务组 8 范畴）",
            file=sys.stderr,
        )
    # 校验变体构造（骨架/二分初始对照）——dry-run 与 live 共用同一构造路径
    for track in ("skeleton", "bisect"):
        if args.track == "both" or args.track == track:
            vs = build_variants(sample, track=track)
            if not vs:
                print(f"错误: 轨道 {track} 变体构造为空", file=sys.stderr)
                return 1
    ticket_evidence = (
        {"ref": args.ticket_ref, "note": args.ticket_note} if args.ticket_ref else None
    )
    report = run_oracle(
        sample,
        budget=args.budget,
        qps=args.qps,
        data_dir=args.data_dir,
        dry_run=args.dry_run,
        track=args.track,
        ticket_evidence=ticket_evidence,
        client_factory=None if args.dry_run else _client_factory(sample.model),
    )
    print(_summary(args, report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
