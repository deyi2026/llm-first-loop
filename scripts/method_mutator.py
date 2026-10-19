#!/usr/bin/env python3
"""方法卡变异器 MVP（确定性算子，不调用 LLM）。

定位：RSI 闭环里的"变异生成器"最小版本，只做**缺陷驱动**的结构修复：
先检测卡片的可机械判定缺陷，再为每个缺陷生成一条最小编辑，输出
METHOD.md + 统一 diff + 理由 + 血统 manifest。

硬约束（与 docs/ANALYSIS-20261019-rsi-self-improvement-requirements.md R1/R4 一致）：
- 变异空间限 METHOD.md 正文段：Trigger / Discriminator / Short path /
  Stop conditions / Verification / Counterexamples。
- frontmatter（method_id、status、evidence_refs、parent_ref 等）**字节级不改**；
  任何算子若会触碰 frontmatter 直接拒绝。
- 不改写语义内容：不虚构证据、不新增事实断言；需要人写的地方留
  TODO 标记并要求 --allow-todo。
- 幂等：修复后重跑同一批算子应检出 0 缺陷。
- 所有产物 review_required=true，不接受自动上线。

用法：
    python3 scripts/method_mutator.py --check --card data/methods/<id>/METHOD.md
    python3 scripts/method_mutator.py --card <METHOD.md> --out data/methods/_candidates \\
        --ops dup,vague,unlinked_ver --json
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

MUTATOR_VERSION = "0.1.0"

REQUIRED_SECTIONS = [
    "Trigger",
    "Discriminator",
    "Short path",
    "Stop conditions",
    "Verification",
    "Counterexamples",
]

# 缺陷 -> 允许的算子名（一条算子只修一类缺陷，便于归因）
OP_FOR_DEFECT = {
    "dup_bullet": "dup",
    "vague_verb": "vague",
    "unlinked_verification": "unlinked_ver",
    "empty_section": "empty",
    "missing_section": "missing",
}

GATE_RULE = re.compile(r"Verification\s*未逐条通过前不结案")
# 元陈述型验证条目（计数/记入信号）不是可执行的检查，不参与"未挂停止条件"判定
META_ITEM = re.compile(r"(记为|计数|视为|用于后续|信号)")

VAGUE_PATTERNS = re.compile(r"(看看|检查一下|注意一下|适当|尽量|酌情|大概|应该没问题|有空再)")


class MutatorError(RuntimeError):
    pass


@dataclass
class Card:
    frontmatter: str
    body: str
    sections: list[tuple[str, list[str]]] = field(default_factory=list)

    @property
    def raw(self) -> str:
        return self.frontmatter + self.body


@dataclass
class Defect:
    kind: str
    section: str
    detail: str
    payload: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "section": self.section, "detail": self.detail}


@dataclass
class Mutation:
    defect: Defect
    edit: dict  # {"op":..., "section":..., "line_index":..., "remove_lines"/"insert_lines": [...]}
    rationale: str
    introduces_todo: bool = False


def parse_card(text: str) -> Card:
    if not text.startswith("---\n"):
        raise MutatorError("缺少 YAML frontmatter（卡片必须以 --- 开头）")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise MutatorError("frontmatter 未闭合")
    frontmatter = text[: end + len("\n---\n")]
    body = text[end + len("\n---\n"):]

    sections: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for line in body.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            current = (m.group(1).strip(), [])
            sections.append(current)
        elif current is not None:
            current[1].append(line)
        else:
            if line.strip():
                raise MutatorError(f"正文出现在第一个 ## 段之前：{line!r}")
    return Card(frontmatter=frontmatter, body=body, sections=sections)


def _bullets(lines: Iterable[str]) -> list[tuple[int, str]]:
    out = []
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("- "):
            out.append((i, s[2:].strip()))
    return out


def detect_defects(card: Card) -> list[Defect]:
    defects: list[Defect] = []
    names = [n for n, _ in card.sections]

    for req in REQUIRED_SECTIONS:
        if req not in names:
            defects.append(Defect("missing_section", req, f"缺少必备段 ## {req}"))
        else:
            body_lines = dict(card.sections)[req]
            if not any(line.strip() for line in body_lines):
                defects.append(Defect("empty_section", req, f"## {req} 为空"))

    seen: dict[str, tuple[str, int]] = {}
    for name, lines in card.sections:
        for idx, text in _bullets(lines):
            key = re.sub(r"\s+", " ", text).strip().lower()
            if len(key) < 16:
                continue
            if key in seen:
                prev_name, _prev_idx = seen[key]
                defects.append(
                    Defect(
                        "dup_bullet",
                        name,
                        f"与 ## {prev_name} 中的条目重复：{text[:40]}…",
                        {"line_index": idx, "text": text},
                    )
                )
            else:
                seen[key] = (name, idx)

    short = dict(card.sections).get("Short path", [])
    for idx, text in _bullets(short):
        hit = VAGUE_PATTERNS.search(text)
        if hit:
            defects.append(
                Defect(
                    "vague_verb",
                    "Short path",
                    f"判据不可核的措辞：{hit.group(0)}",
                    {"line_index": idx, "text": text, "token": hit.group(0)},
                )
            )

    ver = [t for _i, t in _bullets(dict(card.sections).get("Verification", []))]
    stops = " ".join(t for _i, t in _bullets(dict(card.sections).get("Stop conditions", [])))
    if ver and stops and not GATE_RULE.search(stops):
        unlinked = []
        for item in ver:
            tokens = [w for w in re.split(r"[^\w\u4e00-\u9fff]+", item) if len(w) >= 4]
            if META_ITEM.search(item):
                continue
            if tokens and not any(tok in stops for tok in tokens):
                unlinked.append(item)
        if unlinked:
            defects.append(
                Defect(
                    "unlinked_verification",
                    "Verification",
                    f"{len(unlinked)} 条验证条目未被任何 Stop condition 引用：{unlinked[0][:30]}…",
                    {"items": unlinked},
                )
            )
    return defects


def plan_mutations(defects: list[Defect], ops: set[str]) -> list[Mutation]:
    plans: list[Mutation] = []
    for d in defects:
        op = OP_FOR_DEFECT.get(d.kind)
        if op is None or op not in ops:
            continue
        if d.kind == "dup_bullet":
            plans.append(
                Mutation(
                    d,
                    {"op": "delete_line", "section": d.section, "line_index": d.payload["line_index"]},
                    "删除与先前段落完全重复的条目：重复条目会稀释该段的判别力，且违反卡片单义性。",
                )
            )
        elif d.kind == "vague_verb":
            plans.append(
                Mutation(
                    d,
                    {
                        "op": "append_to_line",
                        "section": d.section,
                        "line_index": d.payload["line_index"],
                        "suffix": "；判据：TODO(变异器) 写明可复核的证据形态（命令+期望输出）",
                    },
                    f"「{d.payload['token']}」不可机械判定，补一个待填的判据槽位，迫使写出证据形态。",
                    introduces_todo=True,
                )
            )
        elif d.kind == "unlinked_verification":
            n = len(d.payload.get("items") or [])
            plans.append(
                Mutation(
                    d,
                    {
                        "op": "append_bullet",
                        "section": "Stop conditions",
                        "text": f"Verification 未逐条通过前不结案（覆盖全部 {n} 条验证条目）",
                    },
                    "验证条目没有任何停止条件引用它 = 验证与结案脱钩；补一条把验证结果绑到结案动作的规则。",
                )
            )
        elif d.kind in {"empty_section", "missing_section"}:
            plans.append(
                Mutation(
                    d,
                    {
                        "op": "add_section" if d.kind == "missing_section" else "fill_section",
                        "section": d.section,
                        "text": "TODO(变异器) 该段需人工补全：先用 --check 看缺陷，再按卡片六段式补。",
                    },
                    "段缺失/为空时变异器不编造内容，只占位并标 TODO，防止把模板套话当成方法。",
                    introduces_todo=True,
                )
            )
    return plans


def apply_mutations(card: Card, mutations: list[Mutation]) -> Card:
    sections = [(name, list(lines)) for name, lines in card.sections]
    index = {name: i for i, (name, _) in enumerate(sections)}

    # 删除/追加按行号倒序处理，避免行号漂移
    for m in sorted(
        [m for m in mutations if m.edit["op"] in {"delete_line", "append_to_line"}],
        key=lambda x: (x.edit["section"], x.edit["line_index"]),
        reverse=True,
    ):
        name = m.edit["section"]
        if name not in index:
            continue
        lines = sections[index[name]][1]
        idx = m.edit["line_index"]
        if not (0 <= idx < len(lines)):
            continue
        if m.edit["op"] == "delete_line":
            lines.pop(idx)
        else:
            lines[idx] = lines[idx].rstrip() + m.edit["suffix"]

    for m in mutations:
        if m.edit["op"] != "append_bullet":
            continue
        name = m.edit["section"]
        if name not in index:
            continue
        lines = sections[index[name]][1]
        while lines and not lines[-1].strip():
            lines.pop()
        lines.append("")
        lines.append(f"- {m.edit['text']}")
        lines.append("")

    for m in [m for m in mutations if m.edit["op"] in {"add_section", "fill_section"}]:
        name = m.edit["section"]
        if name in index:
            sections[index[name]][1] = ["", m.edit["text"], ""]
        else:
            sections.append((name, ["", m.edit["text"], ""]))

    order = {n: i for i, n in enumerate(REQUIRED_SECTIONS)}
    sections.sort(key=lambda kv: order.get(kv[0], len(order)))

    body_parts = []
    for name, lines in sections:
        body_parts.append(f"## {name}")
        body_parts.extend(lines)
        if not lines or lines[-1].strip():
            body_parts.append("")
    body = "\n".join(body_parts)
    if not body.endswith("\n"):
        body += "\n"
    return Card(frontmatter=card.frontmatter, body=body, sections=sections)


def make_diff(before: str, after: str, label: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
            n=3,
        )
    )


def _assert_frontmatter_untouched(card: Card, mutated: Card) -> None:
    if card.frontmatter != mutated.frontmatter:
        raise MutatorError("变异触碰了 frontmatter——按 R1 硬约束拒绝产出")
    for bad in ("status:", "method_id:"):
        if bad in mutated.body:
            raise MutatorError(f"正文字段出现保留键 {bad!r}，拒绝产出")


def run(
    card_path: Path,
    out_root: Path | None,
    ops: set[str],
    allow_todo: bool,
    dry_run: bool,
) -> dict:
    text = card_path.read_text(encoding="utf-8")
    card = parse_card(text)
    defects = detect_defects(card)
    plans = plan_mutations(defects, ops)

    if not allow_todo:
        blocked = [p for p in plans if p.introduces_todo]
        if blocked:
            raise MutatorError(
                f"{len(blocked)} 条变异需要人工填 TODO，须显式 --allow-todo 才产出"
            )

    mutated = apply_mutations(card, plans)
    _assert_frontmatter_untouched(card, mutated)

    changed = mutated.body != card.body
    result = {
        "mutator_version": MUTATOR_VERSION,
        "card": str(card_path),
        "parent_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "defects": [d.as_dict() for d in defects],
        "planned": [
            {"defect": p.defect.kind, "op": p.edit["op"], "section": p.edit["section"], "rationale": p.rationale}
            for p in plans
        ],
        "changed": changed,
        "dry_run": dry_run,
    }
    if not changed or dry_run:
        return result

    parent_ref = card_path.parent.name
    candidate_id = _candidate_id(result["parent_sha256"], sorted(ops))
    target = (out_root or (card_path.parent.parent / "_candidates")) / parent_ref / candidate_id
    target.mkdir(parents=True, exist_ok=True)
    (target / "METHOD.md").write_text(mutated.raw, encoding="utf-8")
    (target / "PATCH.diff").write_text(make_diff(text, mutated.raw, "METHOD.md"), encoding="utf-8")
    (target / "RATIONALE.md").write_text(_rationale_md(card_path, plans, defects), encoding="utf-8")
    manifest = {
        "candidate_id": candidate_id,
        "parent_ref": parent_ref,
        "parent_sha256": result["parent_sha256"],
        "candidate_sha256": hashlib.sha256(mutated.raw.encode("utf-8")).hexdigest(),
        "mutator_version": MUTATOR_VERSION,
        "ops": sorted(ops),
        "defects": result["defects"],
        "edits": result["planned"],
        "review_required": True,
        "status": "candidate",
        "created_at": datetime.now(UTC).isoformat(),
    }
    (target / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result.update({"candidate_dir": str(target), "candidate_id": candidate_id})
    return result


def _candidate_id(parent_sha: str, ops: list[str]) -> str:
    h = hashlib.sha256((parent_sha + "|" + ",".join(ops)).encode("utf-8")).hexdigest()[:12]
    return f"mut-{h}"


def _rationale_md(card_path: Path, plans: list[Mutation], defects: list[Defect]) -> str:
    lines = [
        f"# 变异理由 — {card_path.parent.name}",
        "",
        f"mutator {MUTATOR_VERSION}；检出缺陷 {len(defects)} 项，采纳算子 {len(plans)} 条。",
        "",
        "## 逐条",
        "",
    ]
    for p in plans:
        lines += [
            f"### {p.defect.kind} @ {p.edit['section']}",
            "",
            f"- 缺陷：{p.defect.detail}",
            f"- 编辑：`{p.edit['op']}`",
            f"- 理由：{p.rationale}",
            "",
        ]
    lines += [
        "## 未采纳",
        "",
        "- 变异器只做结构修复，不生成新的事实断言、不引入新证据、不改 frontmatter。",
        "- 需要语义改写时由人工或 LLM 变异器另开一轮，产物同样须过预注册评估。",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="方法卡变异器 MVP（确定性、缺陷驱动）")
    ap.add_argument("--card", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--ops", default="dup,vague,unlinked_ver")
    ap.add_argument("--check", action="store_true", help="只报缺陷，不产出候选")
    ap.add_argument("--allow-todo", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    ops = {o.strip() for o in args.ops.split(",") if o.strip()}
    known = set(OP_FOR_DEFECT.values())
    unknown = ops - known
    if unknown:
        print(f"unknown ops: {sorted(unknown)}; known={sorted(known)}", file=sys.stderr)
        return 2

    try:
        res = run(args.card, args.out, ops, args.allow_todo, args.check or args.dry_run)
    except MutatorError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"defects={len(res['defects'])} planned={len(res['planned'])} changed={res['changed']}")
        for d in res["defects"]:
            print(f"  - [{d['kind']}] {d['section']}: {d['detail']}")
        if res.get("candidate_dir"):
            print(f"candidate: {res['candidate_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
