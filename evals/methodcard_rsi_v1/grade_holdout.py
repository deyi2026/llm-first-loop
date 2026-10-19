#!/usr/bin/env python3
"""held-out v1 判分器（纯机械，无 LLM 裁判）。

用法：
    python3 evals/methodcard_rsi_v1/grade_holdout.py --artifact-dir ans/
    python3 evals/methodcard_rsi_v1/grade_holdout.py --selftest
    python3 evals/methodcard_rsi_v1/grade_holdout.py --verify-freeze

约定：
- 每题一个 artifact：<artifact-dir>/<CASE_ID>.json
- 通过 = 该题全部 check 通过（scoring=all_checks_pass）
- 冻结校验失败直接退出 4，不判分（防止偷偷改题）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JSONL = HERE / "heldout_v1.jsonl"
FREEZE = HERE / "FREEZE.json"
EXIT_FREEZE = 4


def load_cases() -> tuple[list[dict], str]:
    raw = JSONL.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if sha != freeze["sha256"]:
        raise SystemExit(
            f"[FREEZE] heldout_v1.jsonl sha256={sha[:16]}… != FREEZE.json {freeze['sha256'][:16]}…；拒绝判分"
        )
    cases = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if len(cases) != freeze["case_count"]:
        raise SystemExit(f"[FREEZE] 用例数 {len(cases)} != 冻结 {freeze['case_count']}")
    return cases, sha


def _value(artifact: dict, field: str):
    if field.endswith("_len"):
        base = field[: -len("_len")]
        v = artifact.get(base)
        return len(v) if isinstance(v, (list, str, dict)) else None
    return artifact.get(field)


def _artifact_text(artifact: dict) -> str:
    return json.dumps(artifact, ensure_ascii=False).lower()


def check_one(case: dict, artifact: dict) -> list[dict]:
    results = []
    inputs = {i["name"]: i for i in case.get("inputs", [])}
    for chk in case["checks"]:
        kind = chk["kind"]
        ok, detail = False, ""
        try:
            if kind == "eq":
                got = _value(artifact, chk["field"])
                ok = got == chk["value"]
                detail = f"{chk['field']}={got!r} want={chk['value']!r}"
            elif kind == "in_set":
                got = _value(artifact, chk["field"])
                ok = got in chk["values"]
                detail = f"{chk['field']}={got!r} in {chk['values']}"
            elif kind == "lte":
                got = _value(artifact, chk["field"])
                ok = isinstance(got, (int, float)) and got <= chk["value"]
                detail = f"{chk['field']}={got!r} <= {chk['value']}"
            elif kind == "gte":
                got = _value(artifact, chk["field"])
                ok = isinstance(got, (int, float)) and got >= chk["value"]
                detail = f"{chk['field']}={got!r} >= {chk['value']}"
            elif kind == "subset_of":
                got = _value(artifact, chk["field"]) or []
                ok = isinstance(got, list) and set(got) <= set(chk["allowed"])
                detail = f"{chk['field']}={got!r} ⊆ {chk['allowed']}"
            elif kind == "regex_absent":
                text = _artifact_text(artifact)
                m = re.search(chk["pattern"], text, re.IGNORECASE)
                ok = m is None
                detail = f"禁用语命中 {m.group(0)!r}" if m else "无禁用表述"
            elif kind == "regex_match":
                text = _artifact_text(artifact)
                ok = re.search(chk["pattern"], text, re.IGNORECASE) is not None
                detail = f"pattern={chk['pattern']}"
            elif kind == "ref_resolves":
                refs = _value(artifact, chk["field"])
                ok = isinstance(refs, list) and len(refs) > 0
                bad = []
                for ref in refs if isinstance(refs, list) else []:
                    m = re.match(r"^([\w./-]+):(\d+)$", str(ref))
                    if not m:
                        bad.append(f"{ref}:格式非法")
                        continue
                    name, line = m.group(1), int(m.group(2))
                    src = inputs.get(name) or next(
                        (v for k, v in inputs.items() if k.endswith(name)), None
                    )
                    if src is None:
                        bad.append(f"{ref}:未知输入")
                    elif line > src["line_count"]:
                        bad.append(f"{ref}:行号越界(≤{src['line_count']})")
                ok = ok and not bad
                detail = "引用可解析" if ok else f"问题引用 {bad[:3]}"
            else:
                detail = f"未知 check kind {kind!r}"
        except Exception as e:  # noqa: BLE001
            detail = f"check 异常：{e}"
        results.append({"check": chk["id"], "kind": kind, "pass": bool(ok), "detail": detail})
    return results


def grade(artifact_dir: Path) -> dict:
    cases, sha = load_cases()
    rows, missing = [], []
    for case in cases:
        path = artifact_dir / f"{case['id']}.json"
        if not path.exists():
            missing.append(case["id"])
            rows.append({"id": case["id"], "family": case["family"], "pass": False,
                         "checks": [], "error": "artifact 缺失"})
            continue
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rows.append({"id": case["id"], "family": case["family"], "pass": False,
                         "checks": [], "error": f"JSON 解析失败：{e}"})
            continue
        checks = check_one(case, artifact)
        rows.append({"id": case["id"], "family": case["family"],
                     "pass": all(c["pass"] for c in checks), "checks": checks})
    passed = sum(1 for r in rows if r["pass"])
    by_family: dict[str, dict] = {}
    for r in rows:
        f = by_family.setdefault(r["family"], {"pass": 0, "total": 0})
        f["total"] += 1
        f["pass"] += 1 if r["pass"] else 0
    return {"heldout_sha256": sha, "total": len(rows), "passed": passed,
            "missing": missing, "by_family": by_family, "cases": rows}


def _synthesize(case: dict) -> dict:
    """按 checks 反推一个能全过的 artifact（仅用于判分器管路自检，不代表题目可答）。"""
    art: dict = {}
    for chk in case["checks"]:
        f, k = chk.get("field", ""), chk["kind"]
        if k == "eq":
            base = f[: -len("_len")] if f.endswith("_len") else f
            if f.endswith("_len"):
                art.setdefault(base, [None] * int(chk["value"]))
            else:
                art[base] = chk["value"]
        elif k == "lte":
            art[f] = chk["value"]
        elif k == "gte":
            base = f[: -len("_len")] if f.endswith("_len") else f
            if f.endswith("_len"):
                art.setdefault(base, [None] * int(chk["value"]))
            else:
                art[base] = chk["value"]
        elif k == "subset_of":
            art.setdefault(f, list(chk["allowed"])[:1] or [])
        elif k == "ref_resolves":
            src = case["inputs"][0]
            art[f] = [f"{src['name']}:1"]
    for chk in case["checks"]:
        f = chk.get("field", "")
        if chk["kind"] == "gte" and f.endswith("_len"):
            base, need = f[: -len("_len")], int(chk["value"])
            cur = list(art.get(base) or [])
            pad = next((c for c in case["checks"]
                        if c["kind"] == "subset_of" and c.get("field") == base), None)
            filler = None
            if pad and pad["allowed"]:
                filler = pad["allowed"][0]
            while len(cur) < need:
                cur.append(filler)
            art[base] = cur
    return art


def selftest() -> int:
    cases, _ = load_cases()
    ok_all = True
    for case in cases:
        good = _synthesize(case)
        res = check_one(case, good)
        if not all(r["pass"] for r in res):
            ok_all = False
            print(f"[SELFTEST] {case['id']} 合成 artifact 未全过：",
                  [(r["check"], r["detail"]) for r in res if not r["pass"]])
        # 扰动：删掉第一个 eq 字段应导致 fail
        eqs = [c for c in case["checks"] if c["kind"] == "eq"]
        if eqs:
            bad = dict(good)
            bad.pop(eqs[0]["field"], None)
            badres = check_one(case, bad)
            if all(r["pass"] for r in badres):
                ok_all = False
                print(f"[SELFTEST] {case['id']} 缺字段仍全过（判分器漏检）")
    print("[SELFTEST]", "PASS（管路自检，非题目可答性证明）" if ok_all else "FAIL")
    return 0 if ok_all else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--verify-freeze", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)

    if args.verify_freeze:
        _, sha = load_cases()
        print(f"FREEZE OK sha256={sha}")
        return 0
    if args.selftest:
        return selftest()
    if not args.artifact_dir:
        ap.print_help()
        return 2

    res = grade(args.artifact_dir)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"passed {res['passed']}/{res['total']}  heldout_sha256={res['heldout_sha256'][:16]}…")
        for fam, v in sorted(res["by_family"].items()):
            print(f"  {fam}: {v['pass']}/{v['total']}")
        for c in res["cases"]:
            if not c["pass"]:
                fails = [f"{x['check']}:{x['detail']}" for x in c["checks"] if not x["pass"]]
                print(f"  FAIL {c['id']} ({c['family']}) {c.get('error','')} {'; '.join(fails)[:160]}")
    if args.strict and res["passed"] != res["total"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
