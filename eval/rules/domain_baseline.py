#!/usr/bin/env python3
"""域内评测快照基线生成器（只读、可复算）。

用途
----
仓库里已散落 48 套域内评测，但**没有一份可复算的聚合基线**：各套件的
判定散落在 `results/`、`*-RESULT*.json`、`BASELINE-*.json` 中，格式不一，
且部分历史基线引用的原始数据文件已缺失（sha256 不可复算）。

本脚本扫描现存套件产物，为每个套件记录：
  - 套件名、产物文件相对路径、文件 sha256、字节数、行数（jsonl）
  - 从可解析的 json/jsonl 中提取的**判定摘要**（decision/verdict/gates 等）
  - 数据完整性状态：ok / missing / unparsable

并输出统一基线文件 `evals/BASELINE-<date>.json`，schema 沿用仓库既有
`lfl-execution-efficiency-v2-baseline/v0.1` 风格（schema/date/source/datasets/
gates/limitations），但**额外要求每个 dataset 的 sha256 现场复算**。

用法
----
    python3 eval/rules/domain_baseline.py --out evals/BASELINE-20261023.json
    python3 eval/rules/domain_baseline.py --verify evals/BASELINE-20261023.json

退出码：0 正常；1 输入不可用。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EVALS = os.path.join(ROOT, "evals")
EXCLUDE_DIRS = {".venv-eval", "__pycache__", ".git"}

# 套件判定摘要要抓的键（按优先级）
DECISION_KEYS = ("decision", "verdict", "status", "outcome", "result")
GATE_KEYS = ("gates", "checks", "criteria")
COUNT_KEYS = ("rows", "cases", "n", "count", "total", "samples")


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pick(d: dict, keys) -> object | None:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def summarize_json(path: str) -> dict:
    """提取判定摘要；不试图重算业务指标（避免假造语义）。"""
    out: dict = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            d = json.load(fh)
    except Exception as e:  # noqa: BLE001
        return {"parse": "failed", "error": str(e)[:160]}
    if not isinstance(d, dict):
        return {"parse": "ok", "type": type(d).__name__,
                "len": len(d) if hasattr(d, "__len__") else None}
    out["parse"] = "ok"
    out["top_level_keys"] = sorted(d.keys())[:24]
    dec = pick(d, DECISION_KEYS)
    if dec is not None:
        out["decision"] = dec if isinstance(dec, (str, int, float, bool)) else f"<{type(dec).__name__}>"
    gates = pick(d, GATE_KEYS)
    if isinstance(gates, dict):
        passed = sum(1 for v in gates.values() if v is True)
        failed = sum(1 for v in gates.values() if v is False)
        out["gates"] = {"n": len(gates), "passed_true": passed, "failed_false": failed}
    elif gates is not None:
        out["gates"] = f"<{type(gates).__name__}>"
    cnt = pick(d, COUNT_KEYS)
    if isinstance(cnt, int):
        out["count"] = cnt
    lim = d.get("limitations")
    if isinstance(lim, list):
        out["limitations_n"] = len(lim)
    return out


def summarize_jsonl(path: str) -> dict:
    out: dict = {"parse": "ok"}
    rows = 0
    keys: set[str] = set()
    verdicts: dict[str, int] = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows += 1
            try:
                obj = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(obj, dict):
                keys.update(list(obj.keys())[:40])
                for vk in ("verdict", "decision", "status", "result", "outcome"):
                    if vk in obj and isinstance(obj[vk], (str, int, float, bool)):
                        verdicts[f"{vk}={obj[vk]}"] = verdicts.get(f"{vk}={obj[vk]}", 0) + 1
    out["rows"] = rows
    out["keys"] = sorted(keys)[:24]
    if verdicts:
        out["value_distribution"] = dict(sorted(verdicts.items(), key=lambda kv: -kv[1])[:12])
    return out


def iter_suites():
    for name in sorted(os.listdir(EVALS)):
        d = os.path.join(EVALS, name)
        if not os.path.isdir(d) or name in EXCLUDE_DIRS or name.startswith("."):
            continue
        yield name, d


def collect() -> dict:
    suites: dict[str, dict] = {}
    artifacts_total = 0
    for name, d in iter_suites():
        arts = []
        for dirpath, dirnames, filenames in os.walk(d):
            dirnames[:] = [x for x in dirnames if x not in EXCLUDE_DIRS]
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                if fn.endswith((".json", ".jsonl")) and os.path.getsize(p) < 20_000_000:
                    arts.append(p)
        # 只保留有判定意义的产物，避免把 .lfldata 噪声算进基线
        keep = [
            p for p in arts
            if re.search(r"(RESULT|BASELINE|GOLDSET|IQ-RESULT|results\.json|summary)", os.path.basename(p), re.I)
        ]
        if not keep:
            keep = arts[:3]
        keep.sort(key=lambda p: -os.path.getsize(p))
        keep = keep[:6]
        entries = []
        for p in keep:
            rel = os.path.relpath(p, ROOT)
            size = os.path.getsize(p)
            ent = {"path": rel, "bytes": size, "sha256": sha256_of(p)}
            try:
                ent["summary"] = (summarize_jsonl(p) if p.endswith(".jsonl")
                                  else summarize_json(p))
            except Exception as e:  # noqa: BLE001
                ent["summary"] = {"parse": "failed", "error": str(e)[:160]}
            entries.append(ent)
            artifacts_total += 1
        suites[name] = {
            "artifacts": entries,
            "n_artifacts_scanned": len(arts),
            "n_artifacts_in_baseline": len(entries),
            "has_runner": any(
                f.startswith("run") and f.endswith(".py")
                for f in os.listdir(d) if f.endswith(".py")
            ),
            "has_freeze": any("FREEZE" in f.upper() for f in os.listdir(d)),
            "has_prereg": any("PREREG" in f.upper() for f in os.listdir(d)),
            "has_protocol": any(f.startswith("PROTOCOL") for f in os.listdir(d)),
        }
    return {"suites": suites, "artifacts_total": artifacts_total}


def cmd_diff(base_path: str, new_path: str) -> int:
    """对比两份基线快照：新增 / 消失 / 变化的套件与产物。

    2026-10-23（P1 出口判据②「48 套基线快照可 diff」）：此前本脚本只有
    --out（生成）与 --verify（校验 sha256 是否仍成立），**没有比对能力** ——
    两份快照之间发生了什么变化无法回答。

    变化判定（逐套件、逐产物）：
      * suite 新增 / 消失
      * 产物路径新增 / 消失
      * 同一路径 sha256 变化（内容被改写）
      * 判定摘要变化（decision/verdict/gates 等）
    """
    old = json.load(open(base_path, encoding="utf-8"))
    new = json.load(open(new_path, encoding="utf-8"))
    old_s = old.get("suites", {})
    new_s = new.get("suites", {})

    added = sorted(set(new_s) - set(old_s))
    removed = sorted(set(old_s) - set(new_s))
    common = sorted(set(old_s) & set(new_s))

    changed_suites: dict[str, list[str]] = {}
    content_changed: list[tuple[str, str, str, str]] = []
    decision_changed: list[tuple[str, str, object, object]] = []

    for sname in common:
        o_art = {a["path"]: a for a in old_s[sname].get("artifacts", [])}
        n_art = {a["path"]: a for a in new_s[sname].get("artifacts", [])}
        notes: list[str] = []
        for p in sorted(set(n_art) - set(o_art)):
            notes.append(f"产物新增 {p}")
        for p in sorted(set(o_art) - set(n_art)):
            notes.append(f"产物消失 {p}")
        for p in sorted(set(o_art) & set(n_art)):
            if o_art[p].get("sha256") != n_art[p].get("sha256"):
                notes.append(f"内容变化 {p}")
                content_changed.append(
                    (sname, p, str(o_art[p].get("sha256")), str(n_art[p].get("sha256")))
                )
            if o_art[p].get("summary") != n_art[p].get("summary"):
                notes.append(f"判定摘要变化 {p}")
                decision_changed.append(
                    (sname, p, o_art[p].get("summary"), n_art[p].get("summary"))
                )
        if notes:
            changed_suites[sname] = notes

    print("═══ 基线快照 diff ═══")
    print(f"基线(旧): {base_path}  （{len(old_s)} 套件）")
    print(f"基线(新): {new_path}  （{len(new_s)} 套件）")
    print(f"\n套件新增: {len(added)}")
    for s in added:
        print(f"  [ADDED]   {s}")
    print(f"套件消失: {len(removed)}")
    for s in removed:
        print(f"  [REMOVED] {s}")
    print(f"套件内容变化: {len(changed_suites)}")
    for s, notes in changed_suites.items():
        print(f"  [CHANGED] {s}")
        for n in notes:
            print(f"      - {n}")
    print(f"\n产物内容变化: {len(content_changed)}   判定摘要变化: {len(decision_changed)}")
    for s, p, o, n in content_changed[:20]:
        print(f"  [SHA]  {s} / {p}\n         old={o[:16]}… new={n[:16]}…")
    for s, p, o, n in decision_changed[:20]:
        print(f"  [DECI] {s} / {p}\n         old={o}\n         new={n}")

    n_diff = len(added) + len(removed) + len(changed_suites)
    print(f"\n[GATE] 基线 diff = {'有差异' if n_diff else '无差异'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--verify", help="校验既有基线文件的 sha256 是否仍成立")
    ap.add_argument("--diff", nargs=2, metavar=("BASE", "NEW"), help="对比两份基线快照")
    args = ap.parse_args()

    if args.diff:
        base_p, new_p = args.diff
        base_p = base_p if os.path.isabs(base_p) else os.path.join(ROOT, base_p)
        new_p = new_p if os.path.isabs(new_p) else os.path.join(ROOT, new_p)
        for p in (base_p, new_p):
            if not os.path.exists(p):
                print(f"[FAIL] 基线文件不存在: {p}", file=sys.stderr)
                return 2
        return cmd_diff(base_p, new_p)

    if args.verify:
        bp = args.verify if os.path.isabs(args.verify) else os.path.join(ROOT, args.verify)
        if not os.path.exists(bp):
            print(f"[FAIL] 基线文件不存在: {bp}", file=sys.stderr)
            return 2
        base = json.load(open(bp, encoding="utf-8"))
        n_ok = n_missing = n_mismatch = 0
        missing, mismatch = [], []
        for sname, s in base.get("suites", {}).items():
            for ent in s.get("artifacts", []):
                p = os.path.join(ROOT, ent["path"])
                if not os.path.exists(p):
                    n_missing += 1
                    missing.append(ent["path"])
                    continue
                if sha256_of(p) == ent.get("sha256"):
                    n_ok += 1
                else:
                    n_mismatch += 1
                    mismatch.append(ent["path"])
        print(f"基线: {bp}")
        print(f"  sha256 一致 : {n_ok}")
        print(f"  文件缺失    : {n_missing}")
        print(f"  sha256 不符 : {n_mismatch}")
        for p in missing[:10]:
            print(f"    [MISSING]   {p}")
        for p in mismatch[:10]:
            print(f"    [MISMATCH]  {p}")
        print()
        print(f"[GATE] 全部可复算 = {'PASS' if (n_missing == 0 and n_mismatch == 0) else 'FAIL'}")
        return 0 if (n_missing == 0 and n_mismatch == 0) else 1

    if not args.out:
        print("[FAIL] 需要 --out 或 --verify", file=sys.stderr)
        return 2

    data = collect()
    suites = data["suites"]
    n_suites = len(suites)
    n_with_runner = sum(1 for s in suites.values() if s["has_runner"])
    n_with_freeze = sum(1 for s in suites.values() if s["has_freeze"])
    n_with_prereg = sum(1 for s in suites.values() if s["has_prereg"])
    n_with_results = sum(
        1 for s in suites.values()
        if any("result" in a["path"].lower() for a in s["artifacts"])
    )
    n_with_decision = sum(
        1 for s in suites.values()
        if any("decision" in a.get("summary", {}) for a in s["artifacts"])
    )

    out = {
        "schema": "lfl-domain-eval-baseline/v0.1",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "scope": "domain-eval-artifacts-only",
        "runtime_mutation": False,
        "tool_visibility_mutation": False,
        "schema_mutation": False,
        "generated_by": "eval/rules/domain_baseline.py",
        "source": {
            "repo_root": ".",
            "suites_scanned": n_suites,
            "artifacts_hashed": data["artifacts_total"],
            "hash_algorithm": "sha256",
        },
        "summary": {
            "n_suites": n_suites,
            "n_suites_with_runner": n_with_runner,
            "n_suites_with_freeze": n_with_freeze,
            "n_suites_with_prereg": n_with_prereg,
            "n_suites_with_results_artifact": n_with_results,
        },
        "gates": {
            # 空套件（仅含 .py/__pycache__，无 json/jsonl 产物）是**真实状态**，
            # 不算失败；故 gate 定义为"有产物的套件必须 100% 登记哈希"。
            "suites_with_artifact_all_hashed": all(
                bool(s["artifacts"]) for s in suites.values() if s["n_artifacts_scanned"] > 0
            ),
            "empty_suites": sorted(
                s for s, v in suites.items() if v["n_artifacts_scanned"] == 0
            ),
            "suites_with_freeze": n_with_freeze,
            "suites_with_prereg": n_with_prereg,
            "suites_without_runner": n_suites - n_with_runner,
            # 判定摘要覆盖：并非每个套件都留有 decision/verdict 字段
            # （浏览器 SMC 类多以 PROTOCOL + results.json 形态存在），
            # 故此 gate 只登记事实，不作通过/失败判定。
            "suites_with_decision_summary": n_with_decision,
        },
        "limitations": [
            "本基线只登记**现存产物**的哈希与判定摘要，不重算业务指标；"
            "指标语义仍以各套件自己的 RESULT/BASELINE 文件为准。",
            "扫描范围内若某套件的原始数据已被删除（历史基线引用的文件缺失），"
            "该套件的旧数字**不可复算**，只能以本基线登记的现存产物为准。",
            "浏览器类套件（smc_*）多数需要浏览器与网络，本基线不含其重跑结果。",
            "本基线不含任何外部公开基准分数。",
        ],
        "suites": suites,
    }

    outp = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    with open(outp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"已写出: {outp}")
    print(f"  套件 {n_suites}（有 runner {n_with_runner} / 有 FREEZE {n_with_freeze} / 有 PREREG {n_with_prereg}）")
    print(f"  哈希产物 {data['artifacts_total']} 个")
    print(f"  gates: {json.dumps(out['gates'], ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
