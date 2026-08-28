#!/usr/bin/env python3
"""CR-R1 shadow A/B: GLM-5.3 / MiniMax-M3 真实长任务（每 provider control/shadow 两阶段）.

用法:
  主模式（分派两阶段子进程）:  python3 scripts/ab_shadow_pilot.py dispatch <tag>
  单阶段模式（被分派调用）:    python3 scripts/ab_shadow_pilot.py phase <tag> <control|shadow> <model>

阶段语义:
  control: COG off 基线（行为/轮次/token——shadow 无干扰对照）
  shadow:  COG shadow + telemetry（同任务: load/barrier/compile/measure, 不改 prompt）

隔离: 每阶段独立子进程 + 独立 LFL_DATA_DIR=data_ab/<tag>/<phase>（fresh session/workspace）。
产物: data_ab/<tag>/report_<phase>_<model-sanitized>.json + 各阶段 data_dir 内 telemetry。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK = """审计任务（多步执行，按顺序完成）：
1. 用 create_goal 创建目标：审计 docs/ 目录下与认知运行时（cognitive runtime / CR-R1）相关文档的验收标准。
2. 用 search_files 在 docs/ 目录按内容关键词 "认知运行时" 检索相关 Markdown 文档。
3. 从结果中选出最多 3 份最相关的，逐个用 read_file 阅读，提取每份的验收标准/不变量要点（每份不超过 3 条）。
4. 每读完一份文档，用 checkpoint_goal 记录一次进度（what=文档名+要点结论）。
5. 全部读完后输出汇总对照表（文档名 → 要点），并用 update_goal 将任务标记 complete。
"""

MODELS = ["glm/glm-5.3", "minimax/MiniMax-M3"]


def run_phase(tag: str, phase: str, model: str) -> dict:
    data_dir = ROOT / "data_ab" / tag / f"{phase}_{model.replace('/', '__')}"
    data_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["LFL_DATA_DIR"] = str(data_dir)
    env["COG_RUNTIME_MODE"] = "off" if phase == "control" else "shadow"
    env["COG_RUNTIME_TELEMETRY"] = "1"
    env["PYTHONPATH"] = str(ROOT / "src")
    proc = subprocess.run(
        [sys.executable, Path(__file__).resolve(), "phase", tag, phase, model],
        env=env, cwd=str(ROOT), capture_output=True, text=True, timeout=3600,
    )
    out = proc.stdout.strip().splitlines()
    payload = {}
    for ln in reversed(out):
        if ln.startswith("PHASE_RESULT "):
            payload = json.loads(ln[len("PHASE_RESULT "):])
            break
    payload["exit_code"] = proc.returncode
    payload["stderr_tail"] = proc.stderr.strip()[-800:]
    return payload


def phase_main(tag: str, phase: str, model: str) -> None:
    # env 已由父进程设置（LFL_DATA_DIR/COG_*）
    load_marker = os.environ.get("COG_RUNTIME_MODE"), os.environ.get("LFL_DATA_DIR")
    from llm_loop.config import load_env_file, load_settings

    load_env_file()  # API keys（env 优先，不覆盖父进程已设值）
    settings = load_settings()
    # CR-R1.1 A/B 教训: Settings.data_dir 不读 LFL_DATA_DIR env（部分模块直读 env 双路径
    # 错位——telemetry/state shard 落镜像主 data/）。显式 replace 统一 data_dir 派生面。
    from dataclasses import replace as _dc_replace

    settings = _dc_replace(
        settings, data_dir=os.environ.get("LFL_DATA_DIR", settings.data_dir)
    )
    print(f"[phase] tag={tag} phase={phase} model={model} cog_mode_env={load_marker[0]} "
          f"data_dir={load_marker[1]}", flush=True)
    from llm_loop.factory import build_engine

    engine = build_engine(settings)
    sid = engine.session.create()
    result = engine.run(sid, TASK, model=model)

    # 采集: usage 实测（event_logs request.usage——引擎逐轮落盘, tokens/cache_hit/miss）。
    # 教训: guarded_requests 每轮 2 行（请求+响应）致轮次虚高一倍; usage_cost.jsonl 引擎不写。
    data_dir = Path(os.environ["LFL_DATA_DIR"])
    el = data_dir / "event_logs" / f"{sid}.jsonl"
    us: list[dict] = []
    if el.exists():
        for x in el.read_text(encoding="utf-8").splitlines():
            if not x.strip():
                continue
            try:
                r = json.loads(x)
            except ValueError:
                continue
            if r.get("type") == "request.usage":
                us.append(r.get("payload") or {})
    telem_rows = []
    telem_p = data_dir / "audit" / "cognitive_telemetry.jsonl"
    if telem_p.exists():
        telem_rows = [json.loads(x) for x in telem_p.read_text(encoding="utf-8").splitlines() if x.strip()]
    pcs = [r for r in telem_rows if r.get("event") == "packet_compile"]
    answer = getattr(result, "final_answer", None) or ""
    report = {
        "tag": tag, "phase": phase, "model": model,
        "rounds": len(us),
        "tokens_in": sum(int(r.get("tokens_in", 0) or 0) for r in us),
        "tokens_out": sum(int(r.get("tokens_out", 0) or 0) for r in us),
        "cache_hit": sum(int(r.get("cache_hit", 0) or 0) for r in us),
        "cache_miss": sum(int(r.get("cache_miss", 0) or 0) for r in us),
        "telemetry_events": len(telem_rows),
        "packet_compile_n": len(pcs),
        "state_rebuild_n": sum(1 for r in telem_rows if r.get("event") == "state_rebuild"),
        "tier_degraded_n": sum(1 for r in telem_rows if r.get("event") == "tier_degraded"),
        "packet_tokens_last": pcs[-1].get("packet_tokens") if pcs else None,
        "goal_id_attribution_ok": bool(pcs and pcs[-1].get("goal_id")),
        "answer_len": len(str(answer)),
        "result_type": type(result).__name__,
    }
    print("PHASE_RESULT " + json.dumps(report, ensure_ascii=False), flush=True)


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "phase":
        phase_main(sys.argv[2], sys.argv[3], sys.argv[4])
        return
    tag = sys.argv[2] if len(sys.argv) > 2 else "p1"
    summary = {"tag": tag, "runs": []}
    # 两阶段顺序: 全部 control 先（Phase A 基线），后 shadow（Phase B）——对齐 benchmark 契约
    for phase in ("control", "shadow"):
        for model in MODELS:
            print(f"[dispatch] {phase} {model} ...", flush=True)
            summary["runs"].append(run_phase(tag, phase, model))
    out_p = ROOT / "data_ab" / tag / "summary.json"
    out_p.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SUMMARY_WRITTEN " + str(out_p), flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
