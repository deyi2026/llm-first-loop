"""方法卡判据 v2：把「未挂」从整段字面子串改为反事实判定。

v1（scripts/method_mutator.detect_defects）的实际判据是：
    验证条目里长度 ≥4 的**无空白片段**必须原样出现在 Stop conditions 的拼接文本中。
中文没有词边界，整句常被切成一两个长 token（例如「根因结论须三证齐备」），因此
Stop 句只要换了措辞就会被判「未挂」。30 张 prereg 卡里 28 张被报缺陷，绝大多数
是措辞重复造成的假阳性。

v2 的判据按**验证条目**逐条给出三分类（judge 输出，模型判定）：
    open       删掉/不执行这条验证，agent 仍可在未观察 X 的情况下结案
    auxiliary  该条是取证动作或报告规范，不是结案前提（不构成缺陷）
    covered    某条 Stop condition 满足时必然已观察到 X（须给 witness 停止条件序号）

detector 自己不判语义，只做确定性校验，把「判定」与「校验」分开：
    1. 卡片全文哈希、每条验证条目哈希必须与 judge 时一致——卡被编辑即 stale 拒绝出结果；
    2. witness_stop 必须在范围内；
    3. witness 不得是通用门禁句（GATE_RULE，如「Verification 未逐条通过前不结案」）：
       它对所有条目一视同仁地成立，不指向任何具体观察，属自指豁免，不能当覆盖证据；
    4. open 条目一条一个 defect（v1 把 1–4 条聚合成一条并截断 detail，清单名义粒度≠实际粒度）。

用法：
    python3 scripts/method_gate_v2.py scan --cards .../prereg_v1_cards.jsonl \
        --spec .../judge_v2_spec.json --out /tmp/v2_scan.json
    python3 scripts/method_gate_v2.py apply --repairs .../repairs_v2.json \
        --cards .../prereg_v1_cards.jsonl --out /tmp/repairs
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import method_mutator as mm  # noqa: E402

LABELS = ("open", "auxiliary", "covered")


class GateError(RuntimeError):
    """schema / 证据不足 / 卡片漂移。"""


def card_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def item_sha(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def verification_items(card) -> list[str]:
    return [t for _i, t in mm._bullets(dict(card.sections).get("Verification", []))]


def stop_items(card) -> list[str]:
    return [t for _i, t in mm._bullets(dict(card.sections).get("Stop conditions", []))]


def _method_id(frontmatter: str) -> str | None:
    m = re.search(r"^method_id:\s*(\S+)", frontmatter, re.M)
    return m.group(1) if m else None


def expand_spec(spec: dict, cards: dict[str, dict]) -> list[dict]:
    """把紧凑 spec 展开成逐条 judge 行。

    spec: {"P01": {"2": {"label": "open", "note": "..."}}, ...}
    未在 spec 中出现的条目记为 covered/inherited（沿用 v1 命中，未做语义复核），
    并在行内如实标注 inherited=True——不把「没复核」伪装成「复核通过」。
    """
    rows: list[dict] = []
    for pair_id, card_info in cards.items():
        card = card_info["card"]
        items = verification_items(card)
        stops = stop_items(card)
        entries = spec.get(pair_id, {})
        row_items = []
        for idx, text in enumerate(items, 1):
            e = entries.get(str(idx))
            if e is None:
                row_items.append(
                    {
                        "i": idx,
                        "text_sha": item_sha(text),
                        "text": text,
                        "label": "covered",
                        "witness_stop": None,
                        "inherited": True,
                        "note": "v1 命中，未做语义复核",
                    }
                )
            else:
                w = e.get("witness")
                witness = w if isinstance(w, int) and 1 <= w <= len(stops) else None
                row_items.append(
                    {
                        "i": idx,
                        "text_sha": item_sha(text),
                        "text": text,
                        "label": e["label"],
                        "witness_stop": witness,
                        "inherited": False,
                        "note": e.get("note", ""),
                    }
                )
        rows.append(
            {
                "pair_id": pair_id,
                "method_id": card_info.get("method_id"),
                "path": str(card_info["path"]),
                "card_sha": card_sha(card_info["text"]),
                "items": row_items,
            }
        )
    return rows


def validate_row(row: dict, card_text: str, card) -> list[str]:
    errors: list[str] = []
    if row.get("card_sha") != card_sha(card_text):
        errors.append("card_sha 不匹配：卡片在 judge 之后被编辑（stale）")
    items = verification_items(card)
    stops = stop_items(card)
    if len(row.get("items", [])) != len(items):
        errors.append(f"条目数不符：judge={len(row.get('items', []))} card={len(items)}")
    for it in row.get("items", []):
        i = it["i"]
        if not (1 <= i <= len(items)):
            errors.append(f"条目序号越界：{i}")
            continue
        if it["text_sha"] != item_sha(items[i - 1]):
            errors.append(f"V{i} 文本哈希不匹配：条目在 judge 之后被编辑")
        if it["label"] not in LABELS:
            errors.append(f"V{i} 非法 label：{it['label']}")
        if it["label"] == "covered":
            w = it.get("witness_stop")
            if w is None:
                if not it.get("inherited"):
                    errors.append(f"V{i} 标 covered 但无 witness 且非 inherited")
            elif not (1 <= w <= len(stops)):
                errors.append(f"V{i} witness_stop 越界：{w}")
            elif mm.GATE_RULE.search(stops[w - 1]):
                errors.append(
                    f"V{i} witness 是通用门禁句（STOP{w}）：不指向具体观察，不能作为覆盖证据"
                )
        elif it.get("witness_stop") is not None:
            errors.append(f"V{i} 标 {it['label']} 却给了 witness")
    return errors


def card_label(items: list[dict]) -> str:
    labels = {it["label"] for it in items}
    if "open" in labels:
        return "true_gap"
    if "auxiliary" in labels:
        return "boundary"
    return "false_positive"


def scan(cards_path: Path, spec_path: Path, strict: bool = True) -> dict:
    rows = [json.loads(line) for line in cards_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    spec = json.loads(spec_path.read_text(encoding="utf-8"))["cards"]
    loaded: dict[str, dict] = {}
    parse_fail: list[dict] = []
    for r in rows:
        text = Path(r["path"]).read_text(encoding="utf-8")
        try:
            card = mm.parse_card(text)
        except mm.MutatorError as exc:
            parse_fail.append({"pair_id": r["pair_id"], "error": str(exc)[:120]})
            continue
        loaded[r["pair_id"]] = {
            "card": card,
            "text": text,
            "path": r["path"],
            "family": r.get("family"),
            "method_id": _method_id(card.frontmatter),
        }
    judge_rows = expand_spec(spec, loaded)
    results = []
    for jr in judge_rows:
        info = loaded[jr["pair_id"]]
        errs = validate_row(jr, info["text"], info["card"])
        if errs and strict:
            raise GateError(f"{jr['pair_id']}: " + "; ".join(errs))
        v1 = [d for d in mm.detect_defects(info["card"]) if d.kind == "unlinked_verification"]
        v1_count = len(v1[0].payload["items"]) if v1 else 0
        open_items = [it for it in jr["items"] if it["label"] == "open"]
        aux_items = [it for it in jr["items"] if it["label"] == "auxiliary"]
        results.append(
            {
                "pair_id": jr["pair_id"],
                "family": info.get("family"),
                "label": card_label(jr["items"]),
                "v1_defect_count": v1_count,
                "open_items": [{"i": it["i"], "text": it["text"], "note": it["note"]} for it in open_items],
                "aux_items": [{"i": it["i"], "text": it["text"][:60]} for it in aux_items],
                "inherited_items": sum(1 for it in jr["items"] if it.get("inherited")),
                "errors": errs,
            }
        )
    summary = {
        "cards": len(results),
        "true_gap": sum(r["label"] == "true_gap" for r in results),
        "boundary": sum(r["label"] == "boundary" for r in results),
        "false_positive": sum(r["label"] == "false_positive" for r in results),
        "v1_cards_with_defect": sum(r["v1_defect_count"] > 0 for r in results),
        "v2_cards_with_defect": sum(bool(r["open_items"]) for r in results),
        "open_items_total": sum(len(r["open_items"]) for r in results),
        "aux_items_total": sum(len(r["aux_items"]) for r in results),
        "parse_fail": parse_fail,
    }
    return {"summary": summary, "judge_rows": judge_rows, "results": results}


def _insert_bullets(text: str, bullets: list[str]) -> str:
    """在 ## Stop conditions 段末尾插入条目，其余字节不动。"""
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## stop"):
            start = i
            break
    if start is None:
        raise GateError("找不到 ## Stop conditions 段")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    block = "".join(f"- {b}\n" for b in bullets)
    if end == len(lines):
        lines.append("\n")
        lines.append(block)
    else:
        lines.insert(end, block)
    return "".join(lines)


def apply_repairs(repairs_path: Path, cards_path: Path, out_dir: Path) -> dict:
    repairs = json.loads(repairs_path.read_text(encoding="utf-8"))["repairs"]
    rowmap = {
        r["pair_id"]: r
        for r in (json.loads(line) for line in cards_path.read_text(encoding="utf-8").splitlines() if line.strip())
    }
    report = []
    for pair_id, spec in repairs.items():
        info = rowmap[pair_id]
        src = Path(info["path"])
        text = src.read_text(encoding="utf-8")
        card = mm.parse_card(text)
        before_fm = card.frontmatter
        before_items = verification_items(card)
        before_stops = stop_items(card)
        bullets = spec["bullets"]
        terms = spec["observable_terms"]
        for b in bullets:
            if not any(t in b for t in terms):
                raise GateError(f"{pair_id}: 补丁句未点名任何 observable：{b[:24]}")
            if mm.GATE_RULE.search(b):
                raise GateError(f"{pair_id}: 补丁句命中 GATE_RULE，禁止用通用门禁句充当修复")
        union_missing = [t for t in terms if not any(t in b for b in bullets)]
        if union_missing:
            raise GateError(f"{pair_id}: observable 未在补丁中出现 {union_missing}")
        new_text = _insert_bullets(text, bullets)
        new_card = mm.parse_card(new_text)
        problems = []
        if new_card.frontmatter != before_fm:
            problems.append("frontmatter 被改动")
        if verification_items(new_card) != before_items:
            problems.append("验证条目被改动")
        after_stops = stop_items(new_card)
        if after_stops[: len(before_stops)] != before_stops:
            problems.append("既有停止条件被改动（只允许追加）")
        for b in bullets:
            if b not in after_stops:
                problems.append(f"补丁句未进入 Stop conditions：{b[:20]}")
        if problems:
            raise GateError(f"{pair_id}: " + "; ".join(problems))
        dst_dir = out_dir / pair_id
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / "METHOD.md"
        dst.write_text(new_text, encoding="utf-8")
        (dst_dir / "PATCH.json").write_text(
            json.dumps(
                {
                    "pair_id": pair_id,
                    "source": str(src),
                    "bullets": bullets,
                    "observable_terms": terms,
                    "rationale": spec.get("rationale", ""),
                    "review": "unreviewed",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        report.append(
            {
                "pair_id": pair_id,
                "out": str(dst),
                "added_stops": [len(before_stops) + k + 1 for k in range(len(bullets))],
                "diff_lines": [f"+ {b}" for b in bullets],
            }
        )
    return {"applied": report}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--cards", required=True)
    s.add_argument("--spec", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--no-strict", action="store_true")
    a = sub.add_parser("apply")
    a.add_argument("--repairs", required=True)
    a.add_argument("--cards", required=True)
    a.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "scan":
        res = scan(Path(args.cards), Path(args.spec), strict=not args.no_strict)
        Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(res["summary"], ensure_ascii=False, indent=2))
    else:
        res = apply_repairs(Path(args.repairs), Path(args.cards), Path(args.out))
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
