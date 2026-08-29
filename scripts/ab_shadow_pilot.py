#!/usr/bin/env python3
"""CR-R1.1 Cognitive Activation A/B (glm-minimax-3): 三形态任务矩阵强制触发 WARM/COLD.

用法:
  dispatch: python3 scripts/ab_shadow_pilot.py dispatch <tag> [--smoke]
  phase:    python3 scripts/ab_shadow_pilot.py phase <tag> <control|shadow> <model> <task> <rep>

任务形态（glm-minimax-3 规格——有效 cognitive sample 须 warm_tokens>0 或 cold_ref_count>0）:
  mem:     save_experience 写经验 → 后续轮经验/记忆匹配注入（tip/memory 槽 → WARM）
  interop: 编程写 interop pending JSON → 引擎每轮重扫注入（HOT/WARM 投影）
  evid:    read_file 超阈值截断落盘 evidence → read_evidence 恢复（RecoveryAction）

矩阵: 2 models × 3 tasks × 2 repeats × 2 phases = 24 runs（--smoke 单任务验证 fixture 有效性）。
隔离: 每 run 独立子进程 + 独立 LFL_DATA_DIR（fresh session/workspace; 注册表经 MODEL_PROVIDERS 注入）。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TASKS: dict[str, str] = {
    "mem": """记忆存取任务（多步执行，按顺序完成）：
1. 用 create_goal 创建目标：验证会话内记忆存取链路。
2. 用 save_experience 记录一条经验：标题「项目审计基准事实」，正文写入三个具体基准数字——测试基线 576 条、认知分层 3 级、工具输出截断阈值 3000 字符，并注明来源为本次审计任务；scenario 填「A/B 记忆链路验证」，solution 填「基准数字已记录」。
3. 用 search_files 在 docs/ 目录按内容关键词「认知运行时」检索，选 1 份最相关文档用 read_file 读取前 60 行，记下其文件名。
4. 现在不重新读取任何先前内容，直接回答：第 2 步记录的三个基准数字分别是什么？第 3 步读的文档文件名是什么？
5. 用 update_goal 将任务标记 complete。最终回答必须包含：三个数字、经验标题、文档文件名、一句「记忆链路验证完成」。
""",
    "interop": """外部协调消息处理任务（多步执行，按顺序完成）：
1. 用 create_goal 创建目标：核实并汇总会话中已注入的 3 条外部协调消息中的事实声明。
2. 3 条协调消息各含一条可核实的声明（涉及项目真实文件）。逐条用 read_file 核实其声明对应的真实文件内容（声明涉及的文件路径已在消息中给出）。
3. 每核实完一条，用 checkpoint_goal 记录（what=消息序号+核实结论+依据）。
4. 用 update_goal 将任务标记 complete。最终回答按条列出：消息序号 → 声明内容 → 核实结论（真/假）→ 依据（文件路径+关键行内容）。
""",
    "evid": """长文远端取证任务（多步执行，按顺序完成）：
1. 用 create_goal 创建目标：验证长文截断后的证据可恢复性。
2. 用 read_file 读取 docs/ai_rules.lite.md（输出会被截断——记住截断提示与恢复方式）。
3. 用 search_files 在 src/ 目录按内容关键词「Read Barrier」检索，记录命中文件名（不少于 1 个）。
4. 验收：用 read_evidence 取回第 2 步被截断的完整原文，回答：(a) 文档最后一个章节/小节的标题与主题；(b) 文中出现的任意 3 条 RULE-AI-XX 规则编号及各自主题；(c) 文档 version 字段值。
5. 用 update_goal 将任务标记 complete。最终回答必须包含：(a)(b)(c) 全部答案 + 一句「证据可恢复性验证完成」。
""",
}

# interop 任务种子: 3 条可核实声明（真实文件 + 真实事实，结论可判定）
INTEROP_SEEDS = [
    {"id": "ab-seed-1", "topic": "coord", "claim": "声明：docs/ai_rules.lite.md 的规则版本号（version）为 6。请核实。",
     "file": "docs/ai_rules.lite.md"},
    {"id": "ab-seed-2", "topic": "coord", "claim": "声明：src/llm_loop/tools/trim.py 中默认工具输出截断阈值（TOOL_TRIM_MAX 默认值）为 3000。请核实。",
     "file": "src/llm_loop/tools/trim.py"},
    {"id": "ab-seed-3", "topic": "coord", "claim": "声明：项目根目录 README.md 采用 Apache-2.0 开源许可证。请核实。",
     "file": "README.md"},
]

MODELS = ["glm/glm-5.3", "minimax/MiniMax-M3"]

# ── 3c 定向: 两-turn memory 任务（真实激活 memory_snapshot → WARM 生产链）──
# 3b 根因: turn 快照在 run 入口（turn 边界）执行且 build_memory_messages 命中才注入；
# 单 turn 任务首入口时库空 → 永不触发。两 turn: t1 撑起完整工具轮 + t2 语义查询，
# t2 入口快照检索命中 driver 预填种子记忆（上游数据预置，同 _seed_interop 先例，
# 非构造注入消息——注入链本身=生产路径）。
TASKS_2T: dict[str, tuple[str, str]] = {
    "mem2t": (
        """记忆存取任务第一阶段（多步执行，按顺序完成）：
1. 用 create_goal 创建目标：验证跨 turn 记忆存取链路。
2. 用 save_experience 记录一条经验：标题「项目审计基准事实」，正文写入三个具体基准数字——测试基线 576 条、认知分层 3 级、工具输出截断阈值 3000 字符；scenario 填「A/B 跨 turn 记忆验证」，solution 填「基准数字已记录」。
3. 用 search_files 在 docs/ 目录按内容关键词「认知运行时」检索，选 1 份最相关文档用 read_file 读取前 40 行，记下其文件名。
4. 用 update_goal 将本阶段标记 complete。最终回答总结：三个基准数字 + 文档文件名 + 一句「第一阶段完成」。
""",
        """记忆存取任务第二阶段：现在不许重新调用 save_experience/search_records/search_archive/read_evidence 检索历史，直接凭你在第一阶段记录的内容与会话内可见的记忆注入回答：
1. 项目审计的三个基准数字分别是什么？各自含义一句话。
2. 第一阶段读的文档文件名是什么？
3. 判断：你的回答依据来自记忆注入还是本轮上下文？一句话说明。
最终回答必须包含三个数字与文档文件名。
""",
    ),
}


def _seed_memory(engine, sid: str) -> None:
    """3c 记忆种子: 预填一条 scope=global 事实记忆（上游数据预置，_seed_interop 先例）.

    快照注入链（检索→wrap→append→packet 投影）全部走生产路径；种子仅保证
    turn 入口检索可命中（fresh data_dir 记忆库为空时单 turn 任务永不触发）。
    """
    from llm_loop.memory.store import MemoryEntry

    engine.memory.save_entry(
        MemoryEntry(
            id="ab-seed-mem-3c",
            type="fact",
            content=(
                "项目审计基准事实：测试基线 576 条；认知分层 3 级；"
                "工具输出截断阈值 3000 字符（2026-08 审计确认，"
                "来源 A/B 跨 turn 记忆验证任务）"
            ),
            keywords=["基准", "数字", "审计", "记忆", "基线", "576"],
            scope="global",
        )
    )

# Recovery 工具白名单（CognitiveOverheadMeter 同源口径）
RECOVERY_TOOLS = {"read_evidence", "search_archive", "search_records"}


def run_phase(tag: str, phase: str, model: str, task: str, rep: int) -> dict:
    data_dir = ROOT / "data_ab" / tag / f"{phase}_{model.replace('/', '__')}__{task}{rep}"
    data_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["LFL_DATA_DIR"] = str(data_dir)
    env["COG_RUNTIME_MODE"] = "off" if phase == "control" else phase  # canary: enforce 透传（driver 子进程边界，不动 src/）
    env["COG_RUNTIME_TELEMETRY"] = "1"
    env["PYTHONPATH"] = str(ROOT / "src")
    # glm-minimax-2 教训: providers.json 定位 {data_dir}/providers.json（优先级 2）——
    # fresh data_dir 隔离把注册表也隔离掉 → 未知 provider 假跑。经优先级 1 注入。
    _providers_p = ROOT / "data" / "providers.json"
    if _providers_p.exists():
        env["MODEL_PROVIDERS"] = _providers_p.read_text(encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, Path(__file__).resolve(), "phase", tag, phase, model, task, str(rep)],
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


def _seed_interop(data_dir: Path) -> None:
    """interop 形态: 任务开始前写 3 条 pending JSON → 引擎首轮 build 重扫注入."""
    pend = data_dir / "interop" / "lfl_to_dsh" / "pending"
    pend.mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(INTEROP_SEEDS, 1):
        msg = {
            "status": "pending",
            "id": s["id"],
            "topic": s["topic"],
            "from": "ab-driver",
            "body": f"{s['claim']}（涉及文件：{s['file']}）",
        }
        (pend / f"seed-{i}.json").write_text(
            json.dumps(msg, ensure_ascii=False), encoding="utf-8"
        )


def phase_main(tag: str, phase: str, model: str, task: str, rep: int) -> None:
    # env 已由父进程设置（LFL_DATA_DIR/COG_*）
    from llm_loop.config import load_env_file, load_settings
    load_env_file()  # API keys（env 优先，不覆盖父进程已设值）
    settings = load_settings()
    # data_dir 双路径修复（8229639）: Settings.data_dir 不读 LFL_DATA_DIR env——
    # 显式 replace 统一 data_dir 派生面（telemetry/state shard/event_logs 落位一致）。
    from dataclasses import replace as _dc_replace

    data_dir_str = os.environ.get("LFL_DATA_DIR", settings.data_dir)
    settings = _dc_replace(settings, data_dir=data_dir_str)
    print(f"[phase] tag={tag} phase={phase} model={model} task={task} rep={rep} "
          f"cog_mode_env={os.environ.get('COG_RUNTIME_MODE')} data_dir={data_dir_str}", flush=True)
    from llm_loop.factory import build_engine
    engine = build_engine(settings)
    if task == "interop":
        _seed_interop(Path(data_dir_str))
    sid = engine.session.create()
    if task == "mem2t":  # 3c 两-turn: 种子预填 + 两次 run（同 sid 同 session，t2 入口触发快照）
        _seed_memory(engine, sid)
        t1, t2 = TASKS_2T[task]
        engine.run(sid, t1, model=model)
        result = engine.run(sid, t2, model=model)
    else:
        result = engine.run(sid, TASKS[task], model=model)
    answer = getattr(result, "final_answer", "")

    # ── 采集 ──
    data_dir = Path(data_dir_str)
    # usage 实测（event_logs request.usage——引擎逐轮落盘, tokens/cache_hit/miss）
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
    # cognitive telemetry
    telem_rows = []
    telem_p = data_dir / "audit" / "cognitive_telemetry.jsonl"
    if telem_p.exists():
        telem_rows = [json.loads(x) for x in telem_p.read_text(encoding="utf-8").splitlines() if x.strip()]
    pcs = [r for r in telem_rows if r.get("event") == "packet_compile"]
    # action_trace: recovery / duplicate tool calls（Efficiency Gate 原始数据）
    at_rows = []
    at_p = data_dir / "audit" / "action_trace.jsonl"
    if at_p.exists():
        at_rows = [json.loads(x) for x in at_p.read_text(encoding="utf-8").splitlines() if x.strip()]
    tc = [r for r in at_rows if r.get("action_type") == "tool_call"]
    tc_names = [str(r.get("detail") or "") for r in tc]
    dup = len(tc_names) - len(set(tc_names))
    report = {
        "tag": tag, "phase": phase, "model": model, "task": task, "rep": rep,
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
        # ── Activation Gate（glm-minimax-3 新增）──
        "hot_active_n": sum(1 for r in pcs if int(r.get("hot_tokens", 0) or 0) > 0),
        "warm_active_n": sum(1 for r in pcs if int(r.get("warm_tokens", 0) or 0) > 0),
        "cold_active_n": sum(1 for r in pcs if int(r.get("cold_ref_count", 0) or 0) > 0),
        "warm_tokens_sum": sum(int(r.get("warm_tokens", 0) or 0) for r in pcs),
        "cold_ref_sum": sum(int(r.get("cold_ref_count", 0) or 0) for r in pcs),
        # ── Efficiency Gate 原始数据 ──
        "tool_calls_n": len(tc),
        "recovery_calls_n": sum(1 for n in tc_names if n in RECOVERY_TOOLS),
        "duplicate_tool_calls_n": dup,
        "answer_len": len(str(answer)),
        "result_type": type(result).__name__,
    }
    print("PHASE_RESULT " + json.dumps(report, ensure_ascii=False), flush=True)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args and args[0] == "phase":
        phase_main(args[1], args[2], args[3], args[4], int(args[5]))
        return
    tag = args[1] if len(args) > 1 else "glm-minimax-3"
    smoke = "--smoke" in sys.argv
    plan: list[tuple[str, str, str, int]] = []
    # 两阶段顺序: 全部 control 先（Phase A 基线），后 shadow——对齐 benchmark 契约
    if smoke:  # fixture 有效性单点验证: 最难形态（evid）× GLM × shadow × 1 rep
        plan = [("shadow", MODELS[0], "evid", 1)]
    elif tag.endswith("-3c"):  # 3c 定向: mem2t only × 8 runs（两阶段契约保持）
        for phase in ("control", "shadow"):
            for model in MODELS:
                for rep in (1, 2):
                    plan.append((phase, model, "mem2t", rep))
    elif tag.endswith("-canary"):  # bounded enforce canary: control(off)→enforce × mem2t 8 runs
        for phase in ("control", "enforce"):
            for model in MODELS:
                for rep in (1, 2):
                    plan.append((phase, model, "mem2t", rep))
    else:
        for phase in ("control", "shadow"):
            for model in MODELS:
                for task in TASKS:
                    for rep in (1, 2):
                        plan.append((phase, model, task, rep))
    summary = {"tag": tag, "runs": []}
    # smoke3 实测单 run ~25min（LLM 大上下文响应为主）→ 24 runs 串行 ~12h 不可接受。
    # 同阶段内并行（不同 run 独立子进程+独立 data_dir 天然隔离；GLM/MiniMax 不同
    # provider 互不干扰限流）；两阶段契约保持: control 全部完成后才 shadow。
    workers = 1 if smoke else 2
    from concurrent.futures import ThreadPoolExecutor
    phases_seq = (
        ("control", "enforce") if tag.endswith("-canary") else ("control", "shadow")
    )
    for phase in phases_seq:
        phase_plan = [p for p in plan if p[0] == phase]
        print(f"[dispatch] phase={phase} n={len(phase_plan)} workers={workers}", flush=True)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(lambda p: run_phase(tag, p[0], p[1], p[2], p[3]), phase_plan))
        summary["runs"].extend(results)
    out_p = ROOT / "data_ab" / tag / "summary.json"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SUMMARY_WRITTEN " + str(out_p), flush=True)


if __name__ == "__main__":
    main()
