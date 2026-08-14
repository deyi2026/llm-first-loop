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
    from llm_loop.config import Settings

    return Settings(
        llm_api_key=key,
        llm_base_url=__import__("os").environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        llm_model=__import__("os").environ.get("LLM_MODEL", "deepseek-v4-flash"),
        data_dir=str(tmp_path / "data"),
        max_iterations=10,
        tool_timeout_s=30.0,
        thinking_mode=__import__("os").environ.get("LLM_THINKING_MODE", "enabled") != "disabled",
        reasoning_effort=__import__("os").environ.get("LLM_REASONING_EFFORT", "high"),
    )


def run_one_sample(prompt: str, workdir: Path, key: str) -> dict:
    """单样本真实执行：engine.run → (trace, answer)。

    会话/数据目录全部隔离到临时目录（M64 防污染真实 data/ 的独立实现）。
    """
    import tempfile

    from llm_loop.factory import build_engine

    tmp = Path(tempfile.mkdtemp(prefix="eval-run-", dir=str(workdir)))
    engine = build_engine(_settings(tmp, key))  # type: ignore[arg-type]
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
    }


def run_dry_sample(prompt: str, workdir: Path, key: str) -> dict:
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
    }


def evaluate(scenarios: dict, *, dry: bool, samples_override: int | None, workdir: Path) -> dict:
    import os

    key = ""
    if not dry:
        key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY", "")
        if not key:
            raise RuntimeError("无真实 LLM key（DEEPSEEK_API_KEY/LLM_API_KEY）；使用 --dry 验证管道")

    runner = run_dry_sample if dry else run_one_sample
    results: list[dict] = []
    for sc in scenarios["scenarios"]:
        n = samples_override if samples_override is not None else int(sc.get("samples", 6))
        per_scenario: list[dict] = []
        for i in range(n):
            sample = runner(sc["prompt"], workdir, key)
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
                }
            )
        k = sum(1 for s in per_scenario if s["verdict"])
        lo, hi = wilson_ci(k, n)
        results.append(
            {
                "id": sc["id"],
                "name": sc["name"],
                "verdict": sc["verdict"],
                "samples": n,
                "passed": k,
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
        "| 场景 | 判定 | 通过/样本 | 率 | Wilson 95% CI |",
        "|:---|:---|:---|:---|:---|",
    ]
    for r in eval_out["results"]:
        lines.append(
            f"| {r['name']} | {r['verdict']} | {r['passed']}/{r['samples']} "
            f"| {r['rate']:.2f} | [{r['ci'][0]:.3f}, {r['ci'][1]:.3f}] |"
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
