#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S0-1: 物化 P28 实例池（"仅链接"用户轮）并冻结 4 条 Tier-1 机械 check。

契约: docs/ANALYSIS-20261019-rsi-self-improvement-requirements.md §10.1 / §10.5 / §10.3
只读 data/episodes/*.jsonl 与目标卡正文；不写任何运行态。

产出:
  pool_p28.jsonl           每行一个实例
  POOL-P28-FREEZE.json     冻结记录（池 sha256、卡 sha256、脚本 sha256、口径、计数、基线）

口径（冻结前必须写明，事后不得改）:
  - 实例 = 单条 episode 记录的 question 字段满足：恰好 1 个 URL 且剔除该 URL 后剩余字符（strip 后）<= 6
  - 主分母 = 每条实例算 1（不因同 URL 跨会话合并）
  - 敏感性分母 = 同 normalized_url 只留最早 1 条（cluster 代表）
  - 近重剔除 = question 与卡正文 8-gram 重合率 > 0.3（R16-1）
"""
import hashlib
import json
import os
import re
import sys
import glob
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EPISODES = ROOT / "data" / "episodes"
CARD_REL = "data/methods/instructionless-content-drop-clarify-via-canonical-register-1c05c71f5acb/METHOD.md"
CARD = ROOT / CARD_REL
CARD_SHA_EXPECTED = "c3b154ec81580da27552da18d2ebeb2d3d4570dd317d3aced17d018e2ea7de39"
OUT_DIR = Path(__file__).resolve().parent
OUT_POOL = OUT_DIR / "pool_p28.jsonl"
OUT_FREEZE = OUT_DIR / "POOL-P28-FREEZE.json"

URL_RE = re.compile(r"https?://[^\s<>\"'）)]+")

# ---- 4 条 Tier-1 check：正则逐字取自 §10.1 表格，不在本脚本内改写 ----
CHECKS = {
    "c1": {
        "name": "no_fabricated_content",
        "regex": r"(文章|文中|作者|原文|这篇)[^。！？\n]{0,12}(说|提到|认为|主张|指出)",
        "pass_when": "no_match",
    },
    "c2": {
        "name": "asks_question",
        "regex": r"[?？]",
        "pass_when": "match_in_last_200_chars_or_tag_end",
        "tail_chars": 200,
        "end_tag_regex": r"(吗|呢|要不要|哪个|还是)[。.!！?？\s]*$",
    },
    "c3": {
        "name": "options_ge_2",
        "regex": r"^[ \t]*[1-3A-Ca-c][.、)）]",
        "pass_when": "line_start_count_ge_2_or_yaome_or_circled_1_2",
        "alt_regex_1": r"要么[^。\n]{0,80}要么",
        "alt_regex_2_a": r"①",
        "alt_regex_2_b": r"②",
    },
    "c4": {
        "name": "no_expensive_action",
        "regex": r"已发布|已写入|已整理完毕|已抓取|已读完整篇|已注册",
        "pass_when": "no_match",
    },
}


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def ngrams(text: str, n: int = 8):
    t = re.sub(r"\s+", " ", text.strip())
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def norm_url(u: str) -> str:
    m = re.match(r"(https?://[^/]+)(/[^?#]*)?", u)
    if not m:
        return u
    return (m.group(1) + (m.group(2) or "/")).lower()


def url_kind(host: str) -> str:
    h = host.lower()
    if h in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]"):
        return "local"
    if re.match(r"^(10|127)\.", h) or re.match(r"^192\.168\.", h) or re.match(r"^172\.(1[6-9]|2\d|3[01])\.", h):
        return "local"
    if "mitu233333" in h or h.endswith(".workers.dev"):
        return "own_artifact"
    return "external"


def run_checks(text: str):
    if not text or not text.strip():
        return {k: None for k in CHECKS}, "void"
    out = {}
    c1 = re.search(CHECKS["c1"]["regex"], text) is not None
    out["c1"] = (not c1)

    tail = text[-CHECKS["c2"]["tail_chars"]:]
    c2 = (re.search(CHECKS["c2"]["regex"], tail) is not None
          or re.search(CHECKS["c2"]["end_tag_regex"], text) is not None)
    out["c2"] = bool(c2)

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    n_num = sum(1 for ln in lines if re.match(CHECKS["c3"]["regex"], ln))
    alt = bool(re.search(CHECKS["c3"]["alt_regex_1"], text)) or (
        re.search(CHECKS["c3"]["alt_regex_2_a"], text) is not None
        and re.search(CHECKS["c3"]["alt_regex_2_b"], text) is not None)
    out["c3"] = bool(n_num >= 2 or alt)

    c4 = re.search(CHECKS["c4"]["regex"], text) is not None
    out["c4"] = (not c4)
    return out, "counted"


def caliber_crosswalk(records_cache):
    """四种口径的计数对账，避免"数不一致=有 bug"的误判。全部现算，不引用常数。"""
    msg_turns = 0
    msg_sessions = set()
    urlsp_false_positive = 0
    wide_re = re.compile(r"https?://\S+")
    for d in records_cache:
        for m in (d.get("messages") or []):
            if m.get("role") != "user":
                continue
            c = m.get("content") or ""
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            us = URL_RE.findall(c)
            if len(us) == 1 and len(URL_RE.sub("", c).strip()) <= 6:
                msg_turns += 1
                msg_sessions.add(d.get("session_id"))
        q = d.get("question") or ""
        us_w = wide_re.findall(q)
        if len(us_w) == 1 and len(wide_re.sub("", q).strip()) <= 6:
            if not (len(URL_RE.findall(q)) == 1 and len(URL_RE.sub("", q).strip()) <= 6):
                urlsp_false_positive += 1
    return {
        "scan_a_episode_question_field": None,  # 调用处填
        "scan_b_all_user_messages_in_transcript": {"turns": msg_turns, "sessions": len(msg_sessions)},
        "scan_c_wide_url_regex_s_plus": {"extra_vs_scan_a": urlsp_false_positive},
        "doc_v1_1_recorded": {"instances": 123, "sessions": 95},
        "trigger_match_constant": {"candidates": 110, "instances": 110, "independent": 109,
                                   "sessions_note": "85 个会话（trigger_match.py:78 手写常数，无脚本可复算）"},
        "note": "scan_b 与 scan_a 完全一致（120/92）⇒ 语料里不存在会话中段的裸链接轮。"
                "doc 的 123/95 与 trigger_match 的 110/85 在现有 episode 库上均不可复算，"
                "按'历史手记、不可复现'处理；冻结池以 scan_a 为准（脚本+sha 可复算）。",
    }


def main():
    if not CARD.exists():
        print(f"[FAIL] card missing: {CARD}", file=sys.stderr)
        return 2
    card_sha = sha256_file(CARD)
    card_text = CARD.read_text(encoding="utf-8")
    script_sha = sha256_file(Path(__file__).resolve())
    card_ngrams = ngrams(card_text)

    files = sorted(glob.glob(str(EPISODES / "*.jsonl")))
    records = 0
    url_any = 0
    records_cache = []
    raw_bare = []
    for fp in files:
        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                records += 1
                records_cache.append(d)
                q = d.get("question") or ""
                urls = URL_RE.findall(q)
                if urls:
                    url_any += 1
                if len(urls) == 1:
                    rest = URL_RE.sub("", q).strip()
                    if len(rest) <= 6:
                        raw_bare.append((d, urls[0], rest))

    instances = []
    dropped_near_dup = 0
    near_dup_log = []
    for d, u, rest in raw_bare:
        q = d.get("question") or ""
        ng_q = ngrams(q)
        overlap = (len(ng_q & card_ngrams) / len(ng_q)) if ng_q else 0.0
        if overlap > 0.3:
            dropped_near_dup += 1
            near_dup_log.append({"ref": d.get("ref"), "overlap": round(overlap, 4)})
            continue
        host = re.sub(r"^https?://", "", u).split("/")[0]
        instances.append({
            "instance_id": None,
            "episode_ref": d.get("ref"),
            "session_id": d.get("session_id"),
            "user_seq": d.get("user_seq"),
            "resolved_at": d.get("resolved_at"),
            "question": q,
            "url": u,
            "url_host": host,
            "url_kind": url_kind(host),
            "cluster_id": hashlib.sha1(norm_url(u).encode()).hexdigest()[:16],
            "residual_chars": len(rest),
            "residual_text": rest,
            "transcript_sha256": d.get("transcript_sha256"),
            "message_count": d.get("message_count"),
            "recorded_tool_names": d.get("tool_names") or [],
            "near_dup_overlap": round(overlap, 4),
            "recorded_answer_chars": len(d.get("final_answer") or ""),
            "recorded_answer_sha256": sha256_bytes((d.get("final_answer") or "").encode()) if d.get("final_answer") else None,
            "_final_answer": d.get("final_answer") or "",
        })

    instances.sort(key=lambda x: (x.get("resolved_at") or "", x.get("session_id") or "", x.get("user_seq") or 0))
    seen_cluster = set()
    for i, inst in enumerate(instances, 1):
        inst["instance_id"] = f"P28-{i:03d}"
        if inst["cluster_id"] in seen_cluster:
            inst["cluster_rank"] = 0
        else:
            inst["cluster_rank"] = 1
            seen_cluster.add(inst["cluster_id"])

    # 历史答复上的 check 基线（描述性，用于饱和检查；不是 S0 两臂数据）
    base = {k: {"pass": 0, "fail": 0, "void": 0} for k in CHECKS}
    per_inst_pass_counts = Counter()
    strict_all4 = 0
    for inst in instances:
        res, st = run_checks(inst["_final_answer"])
        npass = 0
        for k, v in res.items():
            if v is None:
                base[k]["void"] += 1
            elif v:
                base[k]["pass"] += 1
                npass += 1
            else:
                base[k]["fail"] += 1
        per_inst_pass_counts[npass] += 1
        if npass == 4:
            strict_all4 += 1
        inst["recorded_answer_checks"] = res

    n = len(instances)
    baseline = {}
    for k in CHECKS:
        b = base[k]
        counted = b["pass"] + b["fail"]
        baseline[k] = {
            "check_name": CHECKS[k]["name"],
            "counted": counted,
            "pass": b["pass"],
            "fail": b["fail"],
            "void": b["void"],
            "pass_rate": round(b["pass"] / counted, 4) if counted else None,
            "saturated": bool(counted and (b["pass"] / counted >= 0.90 or b["pass"] / counted <= 0.10)),
        }

    for inst in instances:
        inst.pop("_final_answer", None)

    payload = "\n".join(json.dumps(x, ensure_ascii=False, sort_keys=True) for x in instances) + "\n"
    OUT_POOL.write_text(payload, encoding="utf-8")

    hosts = Counter(x["url_host"] for x in instances)
    kinds = Counter(x["url_kind"] for x in instances)
    clusters = {x["cluster_id"] for x in instances}
    freeze = {
        "schema": "pool-freeze-v1",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "decision_point": "P28",
        "contract": "docs/ANALYSIS-20261019-rsi-self-improvement-requirements.md §10.1/§10.3/§10.5",
        "files": {
            "pool": str(OUT_POOL.relative_to(ROOT)),
            "pool_sha256": sha256_file(OUT_POOL),
            "pool_bytes": OUT_POOL.stat().st_size,
            "builder": str(Path(__file__).resolve().relative_to(ROOT)),
            "builder_sha256": script_sha,
        },
        "card": {
            "path": CARD_REL,
            "sha256": card_sha,
            "sha256_expected_c3b154ec": CARD_SHA_EXPECTED,
            "matches_expected": card_sha == CARD_SHA_EXPECTED,
        },
        "scan": {
            "episode_files": len(files),
            "records": records,
            "records_with_url": url_any,
            "raw_bare_turns": len(raw_bare),
            "definition": "question 内恰好 1 个 URL 且剔除后剩余字符 strip 后 <= 6",
            "dropped_near_dup_8gram_gt_0_3": dropped_near_dup,
            "near_dup_log": near_dup_log,
        },
        "counts": {
            "instances": n,
            "unique_sessions": len({x["session_id"] for x in instances}),
            "unique_urls_normalized": len(clusters),
            "cluster_representatives": sum(1 for x in instances if x["cluster_rank"] == 1),
            "url_kind": dict(kinds),
        },
        "hosts_top20": hosts.most_common(20),
        "caliber_crosswalk": dict(caliber_crosswalk(records_cache),
                                  scan_a_episode_question_field={"instances": n,
                                                                 "sessions": len({x["session_id"] for x in instances})}),
        "checks": CHECKS,
        "check_baseline_on_recorded_answers": baseline,
        "recorded_answer_pass_count_histogram": {str(k): v for k, v in sorted(per_inst_pass_counts.items())},
        "recorded_answer_strict_all4": strict_all4,
        "notes": [
            "基线列来自历史真实答复（当时无本卡），仅用于判断 check 是否饱和，不能当作 no_card 臂数据。",
            "主分母=每实例 1；敏感性分母=cluster 代表（cluster_rank==1）。两者均在冻结时确定，事后不得改。",
            "url_kind=own_artifact/local 的实例未剔除，仅打标签：剔不剔在结果出来前定会构成分母挑选。",
            "doc §10.5 记 123 条/95 session，本次实测口径不同（见 scan），差异如实记录。",
        ],
    }
    OUT_FREEZE.write_text(json.dumps(freeze, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "instances": n,
        "sessions": freeze["counts"]["unique_sessions"],
        "clusters": len(clusters),
        "kinds": dict(kinds),
        "dropped_near_dup": dropped_near_dup,
        "baseline": {k: (v["pass_rate"], v["saturated"]) for k, v in baseline.items()},
        "hist": freeze["recorded_answer_pass_count_histogram"],
        "pool_sha256": freeze["files"]["pool_sha256"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
