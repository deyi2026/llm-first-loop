#!/usr/bin/env python3
"""内容级变异器（R3 MVP）：LLM 定向改写一行 → 规则校验 → 产出候选。

为什么需要它（REPORT-20261019 §6 R3）：
v2 的 4 个算子全是字符串模板，23 张卡里有 22 张被追加了同一句「Verification 未逐条
通过前不结案（覆盖全部 N 条验证条目）」。这不是 bug，是模板算子的必然产物：
改动与卡片内容无关，所以它测的不是"方法卡有没有变好"，而是"加一句话有没有副作用"。

本模块把职责切开：
  LLM  只负责「这一行怎么写才修得好这个缺陷」——需要读懂上下文，模板做不到；
  规则 只负责「它说的话是不是新的、编的、越界的」——机械可复算，不靠 LLM 自觉。

校验项（全部机械，`--selftest` 可离线验证）：
  SECTION_NOT_ALLOWED  只允许改 Short path / Verification / Stop conditions / Failure modes
  LINE_MISMATCH        line_index 与原文对不上（防"幻觉行号"）
  MULTILINE            改出一行以上（防夹带整段重写）
  NO_CHANGE            与原文相同（防空改动冒充变异）
  PLACEHOLDER          出现 TODO/TBD/待补/…/示例 等占位
  HEADING              改出小节标题（防改结构）
  NEW_FACT             引入卡里没有的路径/命令/两位数（防编造证据）
  SCHEMA               缺字段、pattern>60 字、insight>120 字或未提缺陷 kind

`yield`（候选产出率）是这层的核心指标：校验失败就返回"没有候选"，绝不回退到模板——
回退正是 v2 出现 22/23 同句的原因。
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ALLOWED_SECTIONS = {"Short path", "Verification", "Stop conditions", "Failure modes"}
PLACEHOLDER = ("TODO", "TBD", "待补", "待填", "……", "…", "示例：", "此处补", "略")
MAX_LINE = 200
MAX_PATTERN = 60
MAX_INSIGHT = 120


# ------------------------------------------------------------------ LLM 调用
def _env() -> dict:
    env = {}
    for line in (REPO / ".env").read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k] = v.split("#")[0].strip().strip('"').strip("'")
    return env


def call_llm(messages: list[dict], max_tokens: int = 4000, attempts: int = 3) -> str:
    env = _env()
    base = env["LLM_BASE_URL"].rstrip("/")
    model = env["LLM_MODEL"].split("/")[-1]
    body = json.dumps({"model": model, "messages": messages, "temperature": 0,
                       "max_tokens": max_tokens}).encode()
    last = ""
    for i in range(attempts):
        try:
            req = urllib.request.Request(base + "/chat/completions", data=body,
                                         headers={"Authorization": "Bearer " + env["GLM_API_KEY"],
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            ch = data["choices"][0]
            txt = (ch["message"].get("content") or "").strip()
            if txt:
                return txt
            last = f"empty content finish={ch.get('finish_reason')}"
            if ch.get("finish_reason") == "length":
                max_tokens = min(max_tokens * 2, 16000)   # reasoning 吃满预算：升了再试
                body = json.dumps({"model": model, "messages": messages, "temperature": 0,
                                   "max_tokens": max_tokens}).encode()
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"llm call failed: {last}")


# ------------------------------------------------------------------ 提示词
PROMPT = """你是方法卡的**定向改写器**。任务：只改一行，修掉一个具体缺陷。

只允许改 `## {section}` 段的第 {line_index} 行（0 起）。这一行现在长这样：
{old_line}

缺陷类型：{kind}
缺陷说明：{detail}
要达成的效果：读卡的人只看这一行，就能判断"这条做没做到"，而不是靠感觉。

卡片全文（只读，供你判断上下文，不要复制其中的空话）：
<<<CARD
{card_text}
CARD

硬约束：
1. 只输出一个 JSON 对象，不要 markdown 代码块；
2. 字段：section / line_index / pattern / insight / new_line；
3. pattern ≤ {max_pattern} 字，是这个改动的"名字"，不要写技术词或模板话；
4. insight ≤ {max_insight} 字，必须说明"为什么这一行改完，上面的缺陷就不成立"，并复述缺陷类型；
5. new_line 必须单行、≤ {max_line} 字符、保留原行的列表符号；不得出现 TODO/TBD/待补/…/示例；
6. 不得新增小节；不得改动 frontmatter；不得引入卡片里没有的命令、路径或多位数字；
7. 如果这一行本来就不该改，输出 {{"abstain": true, "reason": "..."}}。

只输出 JSON。"""


def build_prompt(card_text: str, kind: str, detail: str, section: str,
                 line_index: int, old_line: str) -> str:
    return PROMPT.format(section=section, line_index=line_index, old_line=old_line,
                         kind=kind, detail=detail, card_text=card_text,
                         max_pattern=MAX_PATTERN, max_insight=MAX_INSIGHT, max_line=MAX_LINE)


def parse_json_loose(text: str) -> dict:
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j < 0:
        return {}
    try:
        return json.loads(s[i:j + 1])
    except json.JSONDecodeError:
        return {}


# ------------------------------------------------------------------ 校验
def _facts(text: str) -> set[str]:
    """卡里已有的"可核事实"：路径、反引号内容、≥2 位数字。"""
    out = set(re.findall(r"`([^`]{1,80})`", text))
    out |= set(re.findall(r"(?<![\w.])(/[\w./\-]{2,})", text))
    out |= set(re.findall(r"(?<!\d)(\d{2,})(?!\d)", text))
    return out


def validate_patch(card_text: str, patch: dict, *, kind: str, section: str,
                   line_index: int, old_line: str) -> list[str]:
    v: list[str] = []
    if not isinstance(patch, dict) or not patch:
        return ["SCHEMA:empty"]
    if patch.get("abstain"):
        return ["ABSTAIN"]
    for f in ("section", "line_index", "pattern", "insight", "new_line"):
        if f not in patch:
            v.append(f"SCHEMA:missing_{f}")
    if v:
        return v

    if patch["section"] != section or patch["section"] not in ALLOWED_SECTIONS:
        v.append("SECTION_NOT_ALLOWED")
    if int(patch["line_index"]) != line_index:
        v.append("LINE_MISMATCH")
    new = str(patch["new_line"])
    if "\n" in new or "\r" in new:
        v.append("MULTILINE")
    if new.strip() == old_line.strip():
        v.append("NO_CHANGE")
    if any(t in new for t in PLACEHOLDER):
        v.append("PLACEHOLDER")
    if new.lstrip().startswith("#"):
        v.append("HEADING")
    if len(new) > MAX_LINE:
        v.append("TOO_LONG")
    if len(str(patch["pattern"])) > MAX_PATTERN:
        v.append("PATTERN_TOO_LONG")
    if len(str(patch["insight"])) > MAX_INSIGHT:
        v.append("INSIGHT_TOO_LONG")
    if kind.split("_")[0] not in str(patch["insight"]):
        v.append("INSIGHT_NOT_ABOUT_DEFECT")

    known = _facts(card_text)
    for tok in _facts(new) - known:
        v.append(f"NEW_FACT:{tok[:40]}")
    return v


# ------------------------------------------------------------------ 主流程
def rewrite(card_path: Path, kind: str, detail: str, section: str, line_index: int,
            old_line: str, *, max_repairs: int = 1, llm=call_llm) -> dict:
    card_text = card_path.read_text(encoding="utf-8")
    prompt = build_prompt(card_text, kind, detail, section, line_index, old_line)
    msgs = [{"role": "user", "content": prompt}]
    history = []
    for attempt in range(max_repairs + 1):
        raw = llm(msgs)
        patch = parse_json_loose(raw)
        viol = validate_patch(card_text, patch, kind=kind, section=section,
                              line_index=line_index, old_line=old_line)
        history.append({"attempt": attempt, "raw": raw[:400], "violations": viol})
        if not viol:
            return {"ok": True, "patch": patch, "attempts": attempt + 1, "history": history,
                    "card": str(card_path)}
        if viol == ["ABSTAIN"]:
            return {"ok": False, "abstain": True, "reason": patch.get("reason"),
                    "attempts": attempt + 1, "history": history, "card": str(card_path)}
        msgs = msgs + [{"role": "assistant", "content": raw},
                       {"role": "user", "content": "校验未通过：" + "; ".join(viol)
                        + "。只修这些点，重新输出同一个 JSON。"}]
    return {"ok": False, "violations": viol, "attempts": max_repairs + 1,
            "history": history, "card": str(card_path)}


# ------------------------------------------------------------------ 离线自测
CARD = """---
name: demo
status: active
---
## Short path
- 先跑 `pytest -q evals/methodcard_rsi_v1` 看基线，再改卡。
- 改完卡片后用同一批题复测。
## Verification
- `pytest -q evals/methodcard_rsi_v1` 全绿。
## Stop conditions
- 连续 3 次失败即停。
"""

SELFTEST = [
    ("good", {"section": "Short path", "line_index": 1, "pattern": "复测口径",
              "insight": "vague_verb 的根源是没有可核判据，改成同一批题复测后即可判定",
              "new_line": "- 改完卡片后用同一批题复测，`pytest -q evals/methodcard_rsi_v1` 结果与基线对比。"},
     []),
    ("todo", {"section": "Short path", "line_index": 1, "pattern": "x", "insight": "vague_verb 占位",
              "new_line": "- 改完卡片后 TODO 补测。"}, ["PLACEHOLDER"]),
    ("new_path", {"section": "Short path", "line_index": 1, "pattern": "x", "insight": "vague_verb",
                  "new_line": "- 改完卡片后跑 /usr/local/bin/check.sh 对比。"}, ["NEW_FACT"]),
    ("new_number", {"section": "Short path", "line_index": 1, "pattern": "x", "insight": "vague_verb",
                    "new_line": "- 改完卡片后复测 42 次取中位。"}, ["NEW_FACT"]),
    ("multiline", {"section": "Short path", "line_index": 1, "pattern": "x", "insight": "vague_verb",
                   "new_line": "- 改完复测。\n- 再改。"}, ["MULTILINE"]),
    ("bad_section", {"section": "Header", "line_index": 1, "pattern": "x", "insight": "vague_verb",
                     "new_line": "- 改完复测。"}, ["SECTION_NOT_ALLOWED"]),
    ("no_change", {"section": "Short path", "line_index": 1, "pattern": "x", "insight": "vague_verb",
                   "new_line": "- 改完卡片后用同一批题复测。"}, ["NO_CHANGE"]),
    ("heading", {"section": "Short path", "line_index": 1, "pattern": "x", "insight": "vague_verb",
                 "new_line": "## 复测"}, ["HEADING"]),
]


def selftest() -> int:
    bad = 0
    for name, patch, want in SELFTEST:
        old = "- 改完卡片后用同一批题复测。" if name != "no_change" else "- 改完卡片后用同一批题复测。"
        got = validate_patch(CARD, patch, kind="vague_verb", section="Short path",
                             line_index=1, old_line=old)
        ok = (all(any(g == w or g.startswith(w + ':') for g in got) for w in want)
              if want else got == [])
        print(f"  [{'ok ' if ok else 'FAIL'}] {name:<12} got={got} want={want}")
        bad += 0 if ok else 1
    # abstain 分支
    ab = validate_patch(CARD, {"abstain": True}, kind="vague_verb", section="Short path",
                        line_index=1, old_line="- x")
    ok = ab == ["ABSTAIN"]
    print(f"  [{'ok ' if ok else 'FAIL'}] abstain      got={ab}")
    bad += 0 if ok else 1
    print(f"selftest {len(SELFTEST) + 1 - bad}/{len(SELFTEST) + 1} passed")
    return 0 if bad == 0 else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", type=Path)
    ap.add_argument("--kind")
    ap.add_argument("--detail", default="")
    ap.add_argument("--section")
    ap.add_argument("--line-index", type=int)
    ap.add_argument("--old-line")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    missing = [k for k in ("card", "kind", "section", "old_line") if getattr(args, k) is None]
    if missing:
        ap.error(f"缺少参数 {missing}（或加 --selftest 跑离线校验）")
    out = rewrite(args.card, args.kind, args.detail, args.section,
                  args.line_index or 0, args.old_line)
    print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else out)
    return 0 if out.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
