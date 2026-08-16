"""T4(2026-08-14) 评测运行器：评测集 → 真实 LLM N 样本 → 判定 → Wilson CI → 报告落盘.

用法:
    # 真实 LLM（需 DEEPSEEK_API_KEY/LLM_API_KEY；样本数为场景定义值）
    .venv/bin/python scripts/run_eval.py

    # 指定样本数与输出目录
    .venv/bin/python scripts/run_eval.py --samples 3 --output docs/metrics/eval_20260814

    # dry 模式：内置 fixture 轨迹验证判定/统计/报告管道（零 LLM 零网络）
    .venv/bin/python scripts/run_eval.py --dry

输出:
    <output>/report.json  结构化对账（每场景 k/n + 率 + Wilson CI + 样本详情）
    <output>/report.md    markdown 渲染（CI 区间/基线引用/如实标注）

纪律（playbook 4.x）: 样本不足如实标注；不宣称统计显著（CI 重叠即不显著）；
负结果与正结果同等呈现；报告含评测集版本与场景口径引用。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from llm_loop.eval.verdicts import run_verdict, wilson_ci  # noqa: E402


def load_scenarios(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data.get("scenarios"), list) or not data["scenarios"]:
        raise ValueError(f"评测集为空或格式错误: {path}")
    return data


_SCENARIOS_DEFAULT = Path(__file__).resolve().parent.parent / "tests" / "eval_sets" / "scenarios_v1.json"


def _settings(tmp_path, key: str):
    """真实 LLM Settings（对齐 test_real_llm_smoke._real_llm_settings 口径）."""
    import shutil

    from llm_loop.config import Settings

    # M64 防污染隔离: 会话/审计写临时目录，但 providers.json 复制自真实 data/——
    # 否则多 provider 配置（如 deepseek/deepseek-v4-flash 全限定名）在 L0 合成下
    # resolve 失败"未知 provider"（2026-08-17 实测 401/未知 provider 根因）。
    tmp_data = tmp_path / "data"
    src_providers = Path(__file__).resolve().parent.parent / "data" / "providers.json"
    if src_providers.exists():
        tmp_data.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_providers, tmp_data / "providers.json")

    return Settings(
        llm_api_key=key,
        llm_base_url=__import__("os").environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        # 2026-08-17: strip 防御——shell 环境可能残留带尾随空格的 LLM_MODEL（脏值
        # 被 load_env_file 环境优先跳过覆盖），导致 resolve "模型不存在"（实测根因）。
        llm_model=__import__("os").environ.get("LLM_MODEL", "deepseek-v4-flash").strip(),
        data_dir=str(tmp_data),
        max_iterations=10,
        tool_timeout_s=30.0,
        thinking_mode=__import__("os").environ.get("LLM_THINKING_MODE", "enabled") != "disabled",
        reasoning_effort=__import__("os").environ.get("LLM_REASONING_EFFORT", "high"),
    )


def run_one_sample(prompt: str, workdir: Path, key: str, setup: dict | None = None) -> dict:
    """单样本真实执行：engine.run → (trace, answer)。

    会话/数据目录全部隔离到临时目录（M64 防污染真实 data/ 的独立实现）。
    setup（场景可选）: 运行前向 engine.status 注入失败信号（对齐 M25-M28 必调整基线配置，
    仅测试基建直调 status 公共方法，产品零改动）。
    """
    import tempfile

    from llm_loop.factory import build_engine

    tmp = Path(tempfile.mkdtemp(prefix="eval-run-", dir=str(workdir)))
    engine = build_engine(_settings(tmp, key))  # type: ignore[arg-type]
    if setup:
        _apply_setup(engine, setup)
    sid = engine.session.create()
    result = engine.run(sid, prompt)
    trace = [
        {"name": tc.get("name", ""), "arguments": tc.get("arguments", {})}
        for tc in result.tool_calls
    ]
    return {
        "trace": trace,
        "answer": result.final_answer,
        "model_used": result.model_used,
        "rounds": result.rounds,
        "truncated": result.truncated,
        # A2(2026-08-14): token 用量（prompt 开销指标；0=provider 未提供）
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
    }


def _apply_setup(engine, setup: dict) -> None:
    """场景 setup：向 engine.status 注入失败信号（对齐 M28 基线：2 FAILURE + 1 异常）.

    仅测试基建直调 status 公共方法（record_tool_history/record_exception），产品零改动。
    注入失败 fail-open（status 未装配/异常时跳过，样本照常运行）。
    EVO-20260816-4fb09dd0: setup 含 inject_guidance 时同步注入行动引导
    （"发现失败率偏高/异常 → 应调用 adjust_strategy 调整"），对齐程序给事实、AI 决策。
    """
    try:
        from llm_loop.core.message import ToolResultStatus
        from llm_loop.introspection.status import ToolHistoryItem

        status = getattr(engine, "status", None)
        if status is None:
            return
        n_fail = int(setup.get("inject_failures", 0) or 0)
        for i in range(n_fail):
            status.record_tool_history(
                ToolHistoryItem(
                    name="read_file",
                    arguments={"path": f"/no/such/eval_{i}"},
                    status=ToolResultStatus.FAILURE,
                    summary=f"[文件不存在] /no/such/eval_{i} 不存在（评测预置失败信号）",
                )
            )
        if setup.get("inject_exception"):
            status.record_exception(
                "action.tool_loop", FileNotFoundError("/no/such/eval 预置异常信号")
            )
        # B: 行动引导注入（对齐 HARNESS-04 预警模式——程序给事实，AI 决策）
        if setup.get("inject_guidance"):
            try:
                from llm_loop.core.message import Message, MessageSource

                sess = getattr(engine, "session", None)
                sid = getattr(engine, "session_id", "")
                if sess is not None:
                    msg = Message(
                        role="system",
                        content=(
                            "[行动引导] 检测到工具失败率偏高（2 条 FAILURE）与异常记录。"
                            "若确认异常，应调用 adjust_strategy 调整相关运行参数（如 max_iterations/"
                            "timeout_s）并说明依据——检查后行动，而非仅汇报。"
                        ),
                        source=MessageSource.SYSTEM,
                        metadata={"injected_system": True},
                    )
                    try:
                        sess.messages.append(msg)
                    except Exception:  # noqa: BLE001 — 注入失败 fail-open
                        pass
            except Exception:  # noqa: BLE001 — 引导注入失败 fail-open
                pass
    except Exception:  # noqa: BLE001 — 注入失败 fail-open
        pass


def run_dry_sample(prompt: str, workdir: Path, key: str, setup: dict | None = None) -> dict:
    """dry 模式：固定 fixture 轨迹验证管道（零 LLM；trace 含自查+调整，answer 提及工具名）."""
    return {
        "trace": [
            {"name": "architecture_status", "arguments": {}},
            {"name": "adjust_strategy", "arguments": {"max_iterations": 8}},
            {"name": "read_file", "arguments": {"path": "data/eval_probe.txt"}},
        ],
        "answer": "我通过 architecture_status 自查发现失败率偏高，已用 adjust_strategy 将 max_iterations 从 5 调整为 8。",
        "model_used": "dry-fixture",
        "rounds": 3,
        "truncated": False,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def _dry_injection_selfcheck() -> None:
    """P2-5(2026-08-15): dry 模式注入可见性自检（管道失效如实失败，防 dry 假绿）.

    背景: run_one_sample 依赖 setup 向 engine.status 注入 FAILURE 历史/异常（供
    adjust_step 等必调整场景），而 run_dry_sample 完全不经过注入——若注入链路或
    architecture_status 快照生产路径失效，依赖注入的场景在 dry 下无法被发现。

    自检流程（与 run_one_sample 完全相同的注入调用 + 真实快照生产路径）:
    1. 构造真实 ArchitectureStatusProvider（architecture_status 所用的状态类）
    2. 执行 inject_failures=2 + inject_exception=True 的注入调用（复用 _apply_setup）
    3. 走 architecture_status 快照生产路径（run_status → status_provider.snapshot）
    4. 断言注入的 FAILURE 计数与异常在快照中可见；不可见抛 RuntimeError
       （dry 结果不可信时必须如实失败，不静默通过）。
    """
    from types import SimpleNamespace

    from llm_loop.core.message import ToolResultStatus
    from llm_loop.introspection.status import ArchitectureStatusProvider
    from llm_loop.introspection.tools_status import run_status

    status = ArchitectureStatusProvider(enabled=True)
    _apply_setup(
        SimpleNamespace(status=status),
        {"inject_failures": 2, "inject_exception": True},
    )

    result = run_status(ctx=None, status_provider=status, args={})
    if result.status != ToolResultStatus.SUCCESS:
        raise RuntimeError(
            f"dry 注入自检失败: architecture_status 快照生产失败（status={result.status.value}）"
        )
    try:
        snap = json.loads(result.content)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"dry 注入自检失败: architecture_status 快照解析失败: {exc}") from exc

    tool_history = snap.get("tool_history", [])
    failures = [t for t in tool_history if t.get("status") == ToolResultStatus.FAILURE.value]
    exception_log = snap.get("exception_log", [])
    if len(failures) < 2 or not exception_log:
        raise RuntimeError(
            "dry 注入自检失败: 预置失败信号在 architecture_status 快照中不可见"
            f"（tool_history FAILURE={len(failures)}/2, exception_log={len(exception_log)}/1）"
            "——注入链路或快照生产路径失效，dry 结果不可信（如实失败）。"
        )


def evaluate(scenarios: dict, *, dry: bool, samples_override: int | None, workdir: Path) -> dict:
    import os

    key = ""
    if not dry:
        key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY", "")
        if not key:
            raise RuntimeError("无真实 LLM key（DEEPSEEK_API_KEY/LLM_API_KEY）；使用 --dry 验证管道")
    else:
        # P2-5(2026-08-15): dry 路径开头做注入可见性自检——adjust_step 等依赖预置失败
        # 信号的场景必须在 dry 下同样可被发现（注入不可见 → 如实失败，防 dry 假绿）
        _dry_injection_selfcheck()

    runner = run_dry_sample if dry else run_one_sample
    results: list[dict] = []
    for sc in scenarios["scenarios"]:
        n = samples_override if samples_override is not None else int(sc.get("samples", 6))
        setup = sc.get("setup")
        per_scenario: list[dict] = []
        for i in range(n):
            sample = runner(sc["prompt"], workdir, key, setup)
            verdict = run_verdict(sc["verdict"], sample["trace"], sample["answer"], sc.get("params"))
            per_scenario.append(
                {
                    "sample": i + 1,
                    "verdict": bool(verdict),
                    "trace": sample["trace"],
                    "answer_head": sample["answer"][:200],
                    "model_used": sample["model_used"],
                    "rounds": sample["rounds"],
                    "truncated": sample["truncated"],
                    "tokens_in": sample.get("tokens_in", 0),
                    "tokens_out": sample.get("tokens_out", 0),
                }
            )
        k = sum(1 for s in per_scenario if s["verdict"])
        lo, hi = wilson_ci(k, n)
        # A2: 场景级 token 开销统计（provider 未提供用量时如实 0）
        _toks_in = [s["tokens_in"] for s in per_scenario]
        _toks_out = [s["tokens_out"] for s in per_scenario]
        _toks_total = [a + b for a, b in zip(_toks_in, _toks_out, strict=False)]
        tokens_stats = {
            "total_in": sum(_toks_in),
            "total_out": sum(_toks_out),
            "avg_per_sample": round(sum(_toks_total) / n, 1) if n else 0,
        }
        results.append(
            {
                "id": sc["id"],
                "name": sc["name"],
                "verdict": sc["verdict"],
                "samples": n,
                "passed": k,
                "tokens": tokens_stats,
                "rate": k / n if n else 0.0,
                "ci": [round(lo, 3), round(hi, 3)],
                "samples_detail": per_scenario,
            }
        )
    return {"results": results, "dry": dry}


def render_markdown(scenarios: dict, eval_out: dict) -> str:
    lines = [
        "# 评测报告（T4 评测集运行）",
        "",
        f"> 评测集: {scenarios['name']}（version {scenarios['version']}）",
        f"> 运行模式: {'dry 管道验证（零 LLM）' if eval_out['dry'] else '真实 LLM'}",
        f"> 生成: {datetime.now(UTC).isoformat()}",
        f"> 基线引用: {scenarios.get('baseline_ref', '')}（各验收报告为数据唯一出处）",
        "",
        "| 场景 | 判定 | 通过/样本 | 率 | Wilson 95% CI | 平均 token/样本 |",
        "|:---|:---|:---|:---|:---|:---|",
    ]
    for r in eval_out["results"]:
        lines.append(
            f"| {r['name']} | {r['verdict']} | {r['passed']}/{r['samples']} "
            f"| {r['rate']:.2f} | [{r['ci'][0]:.3f}, {r['ci'][1]:.3f}] "
            f"| {r.get('tokens', {}).get('avg_per_sample', 0):.0f} |"
        )
    lines.append("")
    lines.append("> 纪律：样本不足如实标注；CI 区间重叠即不宣称统计显著；负结果同等呈现。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T4 评测集运行器（真实 LLM / dry 管道验证）")
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=_SCENARIOS_DEFAULT,
    )
    parser.add_argument("--samples", type=int, default=None, help="覆盖场景样本数（默认用场景定义值）")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="报告输出目录（默认 docs/metrics/eval_<ts>/，自动创建）",
    )
    parser.add_argument("--dry", action="store_true", help="dry 模式：fixture 轨迹验证管道（零 LLM）")
    args = parser.parse_args(argv)

    # M63 对齐: 与 CLI/Web/飞书一致从项目 .env 加载（环境变量优先），
    # 真实模式无需手动 export key；--dry 不受影响（不读 key）
    from llm_loop.config import load_env_file

    load_env_file()

    try:
        scenarios = load_scenarios(args.scenarios)
        workdir = Path(__file__).resolve().parent.parent / "data" / "e2e"
        workdir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        out_dir = args.output or (Path(__file__).resolve().parent.parent / "docs" / "metrics" / f"eval_{ts}")
        out_dir.mkdir(parents=True, exist_ok=True)
        eval_out = evaluate(
            scenarios, dry=args.dry, samples_override=args.samples, workdir=workdir
        )
        (out_dir / "report.json").write_text(
            json.dumps(
                {"scenario_version": scenarios["version"], "generated": ts, **eval_out},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (out_dir / "report.md").write_text(render_markdown(scenarios, eval_out), encoding="utf-8")
        print(f"评测完成（{'dry' if args.dry else 'real'}）: {out_dir}")
        for r in eval_out["results"]:
            print(f"  {r['name']}: {r['passed']}/{r['samples']} = {r['rate']:.2f} CI {r['ci']}")
        return 0
    except RuntimeError as exc:
        print(f"评测中止: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — 异常如实报错退出
        print(f"评测异常: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
