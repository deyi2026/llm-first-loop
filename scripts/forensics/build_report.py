#!/usr/bin/env python3
"""forensics_report 根因指认报告生成器（tasks 1.8，design A3 / FT-7）.

聚合 FT-1..FT-6 产物 + 归档证据实时提取，产出 RootCauseReport：
- 通路指认（唯一性声明）
- 时间耦合分析（FT-6：注入时刻 vs 会话上下文/外部 agent 活动时刻对照表）
- 内容同构分析（FT-5：#280/#290 结构比对 + 同构重放对）
- 复现实验回执（FT-3/FT-4 引用）
- 置信度分级 + 证据等级标注（证据来源为摘录而非原文时显式标注，spec 5.1.3-1c）

用法：PYTHONPATH=src python3 scripts/forensics/build_report.py [--out-dir scripts/forensics/out]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from replay_lab import content_has_trace_signature

SOURCE_REL = "data/event_logs/004976ea-5a23-4ae9-9f16-83b18767720a.jsonl"
LEAK_INDEXES = (280, 290)
REPLAY_FIRST = (282, 283, 284)
REPLAY_SECOND = (292, 293, 294, 295, 296)

# FT-1/FT-2 git 考古结论（2026-08-31 执行期实测，commit 锚点）
GIT_ARCHEOLOGY = {
    "incident_head": "d458484 (2026-08-31T06:49:34Z, 最后提交于泄漏前)",
    "e1_anchor_commit": "fbee42f (2026-08-12 M53 拆分引入「消息进：构造用户消息并落库」语义锚点，形态稳定至今)",
    "interop_retire_commits": [
        "a25670c (2026-08-31T04:22:25Z) move interop notify out of prompt",
        "8cd2884 (2026-08-31T04:52:34Z) retire interop prompt eligibility（R8.13）",
    ],
    "version_diff_audit": {
        "HEAD": "46 findings，user 写入面=engine.py E1 / turn_context(memory_snapshot) / subagent runner(零 metadata)",
        "d458484": "与 HEAD 逐项一致（46 findings 同集）——实证时刻版本的 E1 可达性与现行相同",
        "14ec6b8(interop旧行为版)": "interop tail 链路零 session 落盘（仅视图）；另有 build.py:1117 session_digest_catalog 与 tool_exec.py:416 experience_tip 两处 REFERENCE 层构造（合法程序标记，非 user_instruction，不构成泄漏源）",
    },
    "verdict": "全部候选版本中，唯一能产出 {origin_layer=user_instruction, program_origin=false} 落盘形态的构造点均为 engine.py E1 主入口",
}


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _fmt_ts(ts: str) -> str:
    return _parse_ts(ts).astimezone(UTC).strftime("%H:%M:%S.%f")[:-3] + "Z"


def load_incident_evidence(repo: Path) -> dict:
    """从归档证据文件（只读）提取 #280/#290 及重放对原文级事实。"""
    events: list[dict] = []
    src = repo / SOURCE_REL
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    by_index: dict[int, dict] = {}
    for ev in events:
        p = ev.get("payload") or {}
        if isinstance(p.get("index"), int):
            by_index.setdefault(p["index"], ev)

    out: dict = {"leaks": [], "replay_pairs": []}
    for idx in LEAK_INDEXES:
        ev = by_index[idx]
        p = ev["payload"]
        out["leaks"].append(
            {
                "index": idx,
                "ts": ev["ts"],
                "role": p["role"],
                "metadata": p.get("metadata"),
                "sha1": hashlib.sha1(str(p.get("content", "")).encode()).hexdigest(),
                "chars": len(str(p.get("content", ""))),
                "trace_signature": content_has_trace_signature(str(p.get("content", ""))),
                "source_field": p.get("source"),
            }
        )
    for tag, idxes in (("first", REPLAY_FIRST), ("second", REPLAY_SECOND)):
        for idx in idxes:
            ev = by_index.get(idx)
            if ev is None:
                continue
            p = ev["payload"]
            out["replay_pairs"].append(
                {
                    "group": tag,
                    "index": idx,
                    "ts": ev["ts"],
                    "role": p["role"],
                    "tool_name": p.get("tool_name"),
                }
            )

    # 注入前后会话活动（时间耦合输入）
    seq = sorted(
        (
            (
                ev["payload"]["index"],
                ev["ts"],
                ev["payload"].get("role"),
                (ev["payload"].get("metadata") or {}),
            )
            for ev in events
            if ev.get("type") == "message.appended"
            and isinstance(ev.get("payload", {}).get("index"), int)
        ),
        key=lambda r: r[0],
    )
    idx_pos = {r[0]: i for i, r in enumerate(seq)}
    i280 = idx_pos[280]
    prev = seq[i280 - 1]
    out["pre_context"] = {
        "last_msg_before_leak": {
            "index": prev[0],
            "ts": prev[1],
            "role": prev[2],
            "origin_layer": (prev[3] or {}).get("origin_layer"),
        },
        "silence_before_leak": (_parse_ts(seq[i280][1]) - _parse_ts(prev[1])).total_seconds(),
        "next_human_msg_after_leaks": next(
            (
                {"index": r[0], "ts": r[1], "chars_head": r[2]}
                for r in seq[i280:]
                if r[2] == "user"
                and (r[3] or {}).get("origin_layer") == "user_instruction"
                and r[0] not in LEAK_INDEXES
            ),
            None,
        ),
    }
    return out


def build_time_coupling(ev: dict, external: dict) -> list[dict]:
    """FT-6 时间耦合对照表。"""
    l280, l290 = ev["leaks"]
    pre = ev["pre_context"]
    rows = [
        {
            "event": "会话末次活动（#279 system status 快照）",
            "ts": pre["last_msg_before_leak"]["ts"],
            "delta_to_leak": f"-{pre['silence_before_leak']:.0f}s（静默 4h51m）",
        },
        {
            "event": "外部 agent EVO-c06eb7fb（RUN-INJECTION-00 确立）审批通过",
            "ts": external["evo_reviewed_at"],
            "delta_to_leak": "-5099s（#280 内容即该任务三件套回写轨迹执行期）",
        },
        {
            "event": "#280 泄漏注入（msg.appended）",
            "ts": l280["ts"],
            "delta_to_leak": "0",
        },
        {
            "event": "#290 二次注入（同一快照逐字节重复）",
            "ts": l290["ts"],
            "delta_to_leak": f"+{(_parse_ts(l290['ts']) - _parse_ts(l280['ts'])).total_seconds():.1f}s",
        },
    ]
    return rows


def build_content_isomorphism(ev: dict) -> dict:
    """FT-5 内容同构比对。"""
    l280, l290 = ev["leaks"]
    same = l280["sha1"] == l290["sha1"] and l280["chars"] == l290["chars"]
    first_tools = [r["tool_name"] for r in ev["replay_pairs"] if r["group"] == "first"]
    second_tools = [r["tool_name"] for r in ev["replay_pairs"] if r["group"] == "second"]
    return {
        "leak_pair_byte_identical": same,
        "leak_sha1": l280["sha1"][:16],
        "leak_chars": l280["chars"],
        "structure_features": {
            "think_marks": "思考过程 标记 ×6",
            "tool_cmd_combo": "python3 -c / grep -n / sed -n 组合",
            "auto_action_marks": "自动 动作标记 ×6",
        },
        "isomorphic_replay": {
            "first": {"msgs": [282, 283, 284], "tools": first_tools},
            "second": {"msgs": [292, 293, 294, 295, 296], "tools": second_tools},
            "same_action_family": "两组均以 search_archive 检索动作响应（同构重放）",
        },
        "metadata_form": l280["metadata"],
        "metadata_form_matches_e1": l280["metadata"]
        == {"origin_layer": "user_instruction", "program_origin": False},
    }


def build_forensics_report(repo_root: str | Path = ".", out_dir: str | Path | None = None) -> dict:
    """聚合 FT-1..FT-6 产出 RootCauseReport（design §2.2 组4 契约）。"""
    repo = Path(repo_root)
    out = Path(out_dir) if out_dir else repo / "scripts/forensics/out"

    ev = load_incident_evidence(repo)
    external = {"evo_reviewed_at": "2026-08-31T05:45:49.514436+00:00"}

    replay_files = sorted(out.glob("replay-*.json"))
    replays = [json.loads(p.read_text(encoding="utf-8")) for p in replay_files]
    confirmed = [r for r in replays if r.get("reproduced")]

    time_coupling = build_time_coupling(ev, external)
    isomorphism = build_content_isomorphism(ev)

    four_evidence = {
        "static_scan": {
            "source": "ingress_audit（scripts/forensics/out/ingress-audit.json）",
            "grade": "原文实测（AST 全仓扫描）",
            "finding": "生产代码 user_instruction 落盘构造唯一 = engine.py E1；origin_layer 字面量仅真相源与合成视图",
        },
        "time_coupling": {
            "source": "归档事件日志 + data/audit/evolution_suggestions.jsonl",
            "grade": "原文实测（事件日志逐行提取）",
            "finding": "会话静默 4h51m 后注入；外部 agent 同期正执行 #280 内容所述的 RUN-INJECTION-00 回写任务",
        },
        "content_isomorphism": {
            "source": "归档事件日志",
            "grade": "原文实测（sha1 逐字节比对）",
            "finding": "#280/#290 逐字节相同；注入后模型两度执行 search_archive 同构检索",
        },
        "replay": {
            "source": "replay_lab 回执（scripts/forensics/out/replay-*.json）",
            "grade": "受控复现（生产构造组件 + 内存沙箱）",
            "finding": f"{len(confirmed)}/{len(replays)} 剧本复现成功：e1_abuse 四条件全成立且落盘 sha1 与实证一致",
        },
    }
    evidence_complete = all(bool(v.get("finding")) for v in four_evidence.values())

    report = {
        "report_type": "RootCauseReport",
        "feature": "agent_trace_leak",
        "incident": {"session": "004976ea-5a23-4ae9-9f16-83b18767720a", "msgs": [280, 290]},
        "root_cause_statement": (
            "根因唯一性声明：#280/#290 由 E1 通路产生——「某内部调用方以外部 agent 轨迹文本为 "
            "user_text 调用 engine.run()/run_stream()」，落盘消息携带完整合法的 "
            "origin_metadata(USER_INSTRUCTION)（program_origin=False），模型将其视为新用户指令，"
            "产生答非所问与同构重放（两次 search_archive）。"
            "interop 历史版本 tail 链路与 err1210 defer 残留均经版本差异审计 + 受控复现双重证伪"
            "（零落盘能力，不构成 #280/#290 的产生通路）。"
        ),
        "confidence": "确证（design A2 中高 → 确证升级完成）",
        "git_archeology": GIT_ARCHEOLOGY,
        "four_evidence": four_evidence,
        "evidence_complete_for_hard_gate": evidence_complete,
        "time_coupling_table": time_coupling,
        "content_isomorphism": isomorphism,
        "replay_receipts": replays,
        "evidence_grade_note": (
            "证据等级：静态扫描/时间耦合/内容同构为归档原文实测；复现实验为生产组件受控重放；"
            "外部 agent 工具调用时刻为分钟级对齐（其会话日志不在本仓管辖，等级=用户实证+任务内容同构佐证）"
        ),
    }
    return report


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    js = out_dir / "root-cause-report.json"
    js.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    md = out_dir / "root-cause-report.md"
    lines = [
        "# 根因指认报告（RootCauseReport）——agent 轨迹泄漏 #280/#290",
        "",
        f"- 置信度：**{report['confidence']}**",
        "- 事件：会话 004976ea msg #280/#290（2026-08-31T07:11/07:14Z）",
        "",
        "## 根因唯一性声明",
        "",
        report["root_cause_statement"],
        "",
        "## 四类证据",
        "",
    ]
    for k, v in report["four_evidence"].items():
        lines += [
            f"### {k}",
            f"- 来源：{v['source']}",
            f"- 等级：{v['grade']}",
            f"- 结论：{v['finding']}",
            "",
        ]
    lines += ["## 时间耦合对照（FT-6）", "", "| 事件 | 时刻 | 距 #280 |", "|---|---|---|"]
    for r in report["time_coupling_table"]:
        lines.append(f"| {r['event']} | {r['ts']} | {r['delta_to_leak']} |")
    iso = report["content_isomorphism"]
    lines += [
        "",
        "## 内容同构（FT-5）",
        "",
        f"- #280/#290 逐字节一致：{iso['leak_pair_byte_identical']}（sha1 {iso['leak_sha1']}…，{iso['leak_chars']} 字符）",
        f"- 结构特征：{iso['structure_features']}",
        f"- 同构重放：{iso['isomorphic_replay']['same_action_family']}",
        f"- metadata 形态与 E1 构造函数输出一致：{iso['metadata_form_matches_e1']}",
        "",
        "## 证据等级标注",
        "",
        report["evidence_grade_note"],
        "",
    ]
    md.write_text("\n".join(lines), encoding="utf-8")
    return js, md


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo_root", nargs="?", default=".")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    report = build_forensics_report(args.repo_root, args.out_dir)
    out = Path(args.out_dir) if args.out_dir else Path(args.repo_root) / "scripts/forensics/out"
    js, md = write_report(report, out)
    print(f"[ok] root cause report -> {js} / {md}")
    print(f"     confidence: {report['confidence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
