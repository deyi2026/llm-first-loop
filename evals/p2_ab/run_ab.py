#!/usr/bin/env python3
"""P2 A/B 跑批器：同预算两臂对照（baseline vs candidate）。

臂定义（预注册，见 evals/p2_ab/PROTOCOL.md）：
  A 基线   EVIDENCE_MODE=off    —— 现状：压缩后靠 search_archive 自行检索旧证据
  B 候选   EVIDENCE_MODE=enforce —— ERC enforce：压缩后给出有界 recovery capsule
                                    （capture-before-projection），并隐藏 search_archive

同预算：同模型（minimax/MiniMax-M3.1-Flash）、同 max_iterations、同 HISTORY_MAX_CHARS、
同每轮 token 上限 —— 两臂只差 evidence_mode 这一个变量。

用法::

    LLM_MODEL=minimax/MiniMax-M3.1-Flash \
    python3 evals/p2_ab/run_ab.py --arm A --out evals/results/p2ab_v1
    LLM_MODEL=minimax/MiniMax-M3.1-Flash \
    python3 evals/p2_ab/run_ab.py --arm B --out evals/results/p2ab_v1

断点续跑：checkpoint_<arm>.jsonl 已存在的样本跳过（不覆盖、不重跑）。
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.resolve().parents[1]  # evals/p2_ab -> 仓库根
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

ARMS: dict[str, dict] = {
    "A": {
        "label": "baseline: EVIDENCE_MODE=off",
        "env": {"EVIDENCE_MODE": "off"},
    },
    "B": {
        "label": "candidate: EVIDENCE_MODE=enforce",
        "env": {"EVIDENCE_MODE": "enforce", "EVIDENCE_MANIFEST_LIMIT": "12"},
    },
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_events(data_dir: str, sid: str) -> list:
    """读隔离会话的事件日志（压缩事件是事件侧事实，不在 tool trace 里）。

    事件目录：Settings.event_logs_dir 默认 = data_dir/event_logs（可被
    EVENT_LOGS_DIR 覆盖）；这里直接用默认布局，避免构造 Settings 需要凭据参数
    （2026-10-23 实测：Settings(data_dir=...) 缺 llm_api_key 会 TypeError，
    异常被吞掉 → 压缩事件被误记为 0）。
    """
    ok, events = _read_events_ok(data_dir, sid)
    return events


def _read_events_ok(data_dir: str, sid: str) -> tuple[bool, list]:
    """读事件日志并如实回报**读没读到**（读不到 ≠ 没发生压缩）。

    返回 (ok, events)：
      ok=True  → 事件日志读到了（events 可能为空 = 确实没压缩）
      ok=False → 读不到（目录缺失/会话无日志/异常）→ 压缩发生率不可信，报告必须标注
    """
    if not data_dir or not sid:
        return False, []
    try:
        from llm_loop.event_log.store import EventStore

        logs_dir = Path(data_dir) / "event_logs"
        store = EventStore(logs_dir)
        # "读到了"的前提是**该会话确实有日志**（单文件 <sid>.jsonl 或多段目录 <sid>/）。
        # 否则 read() 静默返回空列表 → 会被误读成"读到了、且没发生压缩"。
        exists = (logs_dir / f"{sid}.jsonl").exists() or (logs_dir / sid).is_dir()
        events = list(store.read(sid))
        return bool(exists), events
    except Exception:  # noqa: BLE001 — 事件读不到不伪造（按 0 记并在报告标注）
        return False, []


def _events_ok(data_dir: str, sid: str) -> bool:
    """事件日志是否读到（2026-10-23 复审 P0-A：此前被调用但从未定义 → 跑批器首个样本即 NameError）。"""
    ok, _ = _read_events_ok(data_dir, sid)
    return ok


def _tool_outputs(events: list) -> list[tuple[str, str]]:
    """从事件日志取工具回执正文：[(tool_name, content)]。

    工具输出不在 engine.run 的 tool_calls 里（只有声明参数），只在会话事件日志里
    （role=tool 的 message.appended）。动态金标准（如"一次性随机值"）必须从回执正文取。
    """
    out: list[tuple[str, str]] = []
    for e in events:
        if getattr(e, "type", "") != "message.appended":
            continue
        pl = getattr(e, "payload", {}) or {}
        if pl.get("role") != "tool":
            continue
        name = str(pl.get("tool_name") or "")
        content = str(pl.get("content") or "")
        if name and content:
            out.append((name, content))
    return out


def _dynamic_gold(spec: dict, outputs: list[tuple[str, str]]) -> str:
    """按 {tool, match} 从工具回执里取动态金标准。

    match: first_token —— 回执正文里第一个空白分隔的 token（如随机数）
           first_line  —— 回执正文第一行（去掉首尾空白）
    取不到 → 返回空串（该样本判失败，并在记录里写明 gold=""，不静默通过）。
    """
    tool = spec.get("tool", "execute_command")
    match = spec.get("match", "first_token")
    for name, content in outputs:
        if name != tool:
            continue
        text = content.strip()
        if not text:
            continue
        if match == "first_line":
            return text.splitlines()[0].strip()
        if match.startswith("after_marker:"):
            marker = match.split(":", 1)[1]
            for nm, cont in outputs:
                if nm != tool:
                    continue
                for line in cont.splitlines():
                    if marker in line:
                        # 工具回执里"命令回显"与"实际输出"都含 marker → 取**最后一次**出现
                        # 之后的 token（回显在前，输出在后）。
                        tail = line.rsplit(marker, 1)[1].strip()
                        if tail:
                            return tail.split()[0]
            return ""
        return text.split()[0].strip()
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="P2 A/B 跑批器")
    ap.add_argument("--arm", required=True, choices=sorted(ARMS))
    ap.add_argument("--scenarios", default=str(_HERE / "scenarios_p2ab_v1.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", type=int, default=0, help="覆盖每场景样本数（调试用；正式跑不传）")
    ap.add_argument("--only", default="", help="只跑指定场景 id（逗号分隔）")
    args = ap.parse_args()

    from llm_loop.config import load_env_file
    from llm_loop.eval.verdicts import run_verdict

    load_env_file()
    re_mod = _load("lfl_run_eval", _ROOT / "scripts" / "run_eval.py")
    key = re_mod._resolve_api_key()
    if not key:
        print("[FATAL] 无 LLM key（MINIMAX_API_KEY 等）", file=sys.stderr)
        return 2

    spec = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))
    arm = ARMS[args.arm]
    # 臂变量优先：default_env 不得覆盖 EVIDENCE_MODE（否则两臂差异被悄悄抹掉）
    base_env = {**spec.get("default_env", {}), **arm["env"]}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ck_path = out / f"checkpoint_{args.arm}.jsonl"
    done: set[str] = set()
    if ck_path.exists():
        # 半行容错：kill -9 最常见落点是最后一行写了一半 → 跳过该行，不让续跑整体崩
        for line in ck_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                done.add(json.loads(line)["sample_key"])
            except ValueError:
                continue
        print(f"[resume] {args.arm} 已有 {len(done)} 条，跳过", flush=True)

    only = {s for s in args.only.split(",") if s}
    workdir = out / f"work_{args.arm}"
    workdir.mkdir(parents=True, exist_ok=True)

    # 两臂只差 evidence_mode/manifest_limit/history_max_chars —— 其它字段沿用
    # run_eval 的默认构造（与 P1/P3 跑批同口径）。
    orig_settings = re_mod._settings

    # 当前样本生效的 env（场景级 env 可覆盖默认；臂变量不被覆盖）
    current_env: dict[str, str] = dict(base_env)

    def _patched(tmp_path, k, max_iterations: int = 10):
        s = orig_settings(tmp_path, k, max_iterations=max_iterations)
        env = current_env
        return dataclasses.replace(
            s,
            evidence_mode=env.get("EVIDENCE_MODE", "off"),
            evidence_manifest_limit=int(env.get("EVIDENCE_MANIFEST_LIMIT", "8")),
            history_max_chars=int(env["HISTORY_MAX_CHARS"])
            if env.get("HISTORY_MAX_CHARS")
            else None,
        )

    re_mod._settings = _patched

    n_new = 0
    for sc in spec["scenarios"]:
        if only and sc["id"] not in only:
            continue
        samples = int(args.samples or sc.get("samples", 5))
        for i in range(1, samples + 1):
            key_id = f"{sc['id']}#{i}"
            if key_id in done:
                continue
            # 场景级 env 覆盖默认 env，但**不覆盖臂变量**（EVIDENCE_MODE 是两臂唯一差异）
            env = {**base_env, **sc.get("env", {})}
            env.update(arm["env"])
            current_env.clear()
            current_env.update(env)
            saved = dict(os.environ)
            os.environ.update(env)
            t0 = time.time()
            try:
                sample = re_mod.run_one_sample(
                    sc["prompt"],
                    workdir,
                    key,
                    sc.get("setup"),
                    int(sc.get("max_iterations", 10)),
                )
            finally:
                os.environ.clear()
                os.environ.update(saved)

            events = _read_events(sample.get("data_dir", ""), sample.get("sid", ""))
            outputs = _tool_outputs(events)
            params = dict(sc.get("params") or {})
            gold = ""
            gold_spec = params.pop("gold_from_tool_output", None)
            if gold_spec:
                gold = _dynamic_gold(gold_spec, outputs)
                if gold:
                    params["must_contain"] = list(params.get("must_contain", [])) + [gold]
                    params.setdefault("min_hits", len(params["must_contain"]))
            verdict = bool(run_verdict(sc["verdict"], sample["trace"], sample["answer"], params))
            comp = [e for e in events if getattr(e, "type", "") == "context.compressed"]
            # 归档条目：消息走 ARC-* 归档号，工具调用走 tool_call_id；
            # evidence_ref 字段在多数条目为 null（ERC enforce 才会建 Evidence 引用）。
            archived = [
                str(e.payload.get("evidence_ref") or e.payload.get("archive_ref"))
                for e in comp
                if (e.payload.get("evidence_ref") or e.payload.get("archive_ref"))
            ]
            n_read_evidence = sum(1 for tc in sample["trace"] if tc.get("name") == "read_evidence")
            n_search_archive = sum(1 for tc in sample["trace"] if tc.get("name") == "search_archive")
            retrieved = [
                str(tc.get("arguments", {}).get("evidence_ref"))
                for tc in sample["trace"]
                if tc.get("arguments", {}).get("evidence_ref")
            ]
            rec = {
                "sample_key": key_id,
                "arm": args.arm,
                "arm_label": arm["label"],
                "scenario_id": sc["id"],
                "sample_idx": i,
                "verdict": verdict,
                "truncated": bool(sample["truncated"]),
                "rounds": sample["rounds"],
                "tokens_in": sample.get("tokens_in", 0),
                "tokens_out": sample.get("tokens_out", 0),
                "model_used": sample["model_used"],
                "tool_names": sorted({tc.get("name", "") for tc in sample["trace"]}),
                "n_tool_calls": len(sample["trace"]),
                "n_read_evidence": n_read_evidence,
                "n_search_archive": n_search_archive,
                "compaction_events": len(comp),
                "events_read_ok": _events_ok(sample.get("data_dir", ""), sample.get("sid", "")),
                "archived_refs": archived,
                "retrieved_refs": retrieved,
                # 存续口径（可核）：压缩发生后，模型是否**取回过**归档内容
                # （read_evidence 取具体证据，或 search_archive 检索历史）；
                # 精确 ref 交集在 off 臂通常为空（归档的是工具调用，非 Evidence），
                # 故以"是否发生过取回动作"为事件侧事实，最终正确性由金标准另行判定。
                "survived_compaction": bool(archived)
                and (n_read_evidence > 0 or n_search_archive > 0),
                "gold": gold,
                "n_tool_outputs": len(outputs),
                "answer_len": len(sample["answer"] or ""),
                "answer_head": (sample["answer"] or "")[:400],
                "env": env,
                "elapsed_s": round(time.time() - t0, 1),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            with ck_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_new += 1
            print(
                f"[{args.arm}] {key_id} verdict={verdict} trunc={rec['truncated']} "
                f"rounds={rec['rounds']} compact={rec['compaction_events']} "
                f"survived={rec['survived_compaction']} tools={len(rec['tool_names'])} "
                f"{rec['elapsed_s']}s",
                flush=True,
            )

    print(f"[{args.arm}] 本次新增 {n_new} 条 → {ck_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
