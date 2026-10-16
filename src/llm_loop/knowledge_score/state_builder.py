"""知识卡 + 使用回执 → 独立打分 state 组装器.

卡片两类（只读，绝不写回卡片文件）：
- 经验卡: <root>/experiences/*.md，front matter 含
  title/scenario/root_cause/solution/evidence/tags/status/record_kind
- 方法卡: <root>/data/methods/<id>/METHOD.md（runtime 优先）与
  <root>/methods/<id>/METHOD.md（seed），front matter 含
  name/method_id/description/status

使用记录来自两侧 use ledger（use_ledger.py 定义的行 schema，运行时路径约定：
experiences/usage.jsonl 与 data/methods/usage.jsonl）。

state 三段式（协议样例 tmp/startlux/bench_scoring.py）：
任务背景 → 使用的知识条目要点 → 实际使用结果。单卡多条使用记录时
每条使用记录独立生成一个 state（一对多，不合并）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

_DECISION_ZH = {
    "applied": "直接采用",
    "adapted": "改造后采用",
    "not_applicable": "判定不适用(未采用)",
    "rejected": "明确拒绝",
}

_BENEFIT_ZH = {
    "helped": "有帮助",
    "neutral": "无差别",
    "hindered": "有妨害",
    "unknown": "未说明",
    "mixed": "混合(部分有帮助部分有妨害)",
}

_FIELD_LIMIT = 600
_NOTE_LIMIT = 1200
_STATE_LIMIT = 4000


class CardParseError(Exception):
    """知识卡解析失败（front matter 缺失/格式非法）。"""


def _unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        if text[0] == '"':
            return text[1:-1].replace('\\"', '"')
        return text[1:-1]
    return text


def _parse_scalar(value: str):
    """标量值: [a, b] 列表 / {} 空表 / 去引号字符串。"""
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_unquote(item) for item in inner.split(",") if item.strip()]
    if text == "{}":
        return {}
    return _unquote(text)


def parse_front_matter(text: str) -> tuple[dict, str]:
    """极简 YAML front matter 解析.

    口径与 experiences/document.py 的主链路解析器对齐（本模块自持实现，
    不 import 其私有函数）：key: value / key: [list] / key: {} /
    key: |（或 >、|-、>-）块标量 / key: 一层缩进嵌套块。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise CardParseError("缺少 front matter 起始标记 '---'")
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        raise CardParseError("缺少 front matter 结束标记 '---'")
    fm_lines = lines[1:end]
    meta: dict = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        if not line.strip():
            i += 1
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            raise CardParseError(f"front matter 行格式非法: {line!r}")
        key = key.strip()
        value = value.strip()
        if value[:1] in ("|", ">"):
            # 块标量：| 保留换行；> 折叠为空格（忽略 chomping 指示符差异，
            # 打分 state 只取文本内容）
            i += 1
            block: list[str] = []
            while i < len(fm_lines) and fm_lines[i][:1] in (" ", "\t"):
                block.append(fm_lines[i].strip())
                i += 1
            joiner = "\n" if value[:1] == "|" else " "
            meta[key] = joiner.join(block)
            continue
        if value == "":
            i += 1
            nested: dict = {}
            while i < len(fm_lines) and fm_lines[i][:1] in (" ", "\t"):
                inner = fm_lines[i].strip()
                inner_key, inner_sep, inner_value = inner.partition(":")
                if not inner_sep:
                    raise CardParseError(f"嵌套块行格式非法: {fm_lines[i]!r}")
                nested[inner_key.strip()] = _parse_scalar(inner_value)
                i += 1
            meta[key] = nested
            continue
        meta[key] = _parse_scalar(value)
        i += 1
    body = "\n".join(lines[end + 1 :]).strip()
    return meta, body


@dataclass(frozen=True)
class CardInfo:
    """一张知识卡的只读投影（version = 打分时点整文件内容 sha256）。"""

    kind: str  # "experience" | "method"
    ref: str  # experience:<stem> / method:<id>
    slug: str  # sidecar 文件名用（stem / method_id）
    title: str
    description: str = ""
    scenario: str = ""
    root_cause: str = ""
    solution: str = ""
    evidence: str = ""
    status: str = ""
    record_kind: str = ""
    tags: tuple[str, ...] = ()
    body: str = ""
    path: str = ""
    version: str = ""
    extra: dict = field(default_factory=dict)


def _clip(text: str, limit: int = _FIELD_LIMIT) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def load_experience_card(md_path: Path) -> CardInfo:
    raw = md_path.read_text(encoding="utf-8")
    meta, body = parse_front_matter(raw)
    stem = md_path.name.removesuffix(".md")
    tags = meta.get("tags")
    return CardInfo(
        kind="experience",
        ref=f"experience:{stem}",
        slug=stem,
        title=str(meta.get("title") or stem),
        scenario=str(meta.get("scenario") or ""),
        root_cause=str(meta.get("root_cause") or ""),
        solution=str(meta.get("solution") or ""),
        evidence=str(meta.get("evidence") or ""),
        status=str(meta.get("status") or ""),
        record_kind=str(meta.get("record_kind") or "experience"),
        tags=tuple(str(t) for t in tags) if isinstance(tags, list) else (),
        body=body,
        path=str(md_path),
        version=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def load_method_card(md_path: Path) -> CardInfo:
    raw = md_path.read_text(encoding="utf-8")
    meta, body = parse_front_matter(raw)
    method_id = str(
        meta.get("method_id") or meta.get("name") or md_path.parent.name
    ).strip().lower()
    return CardInfo(
        kind="method",
        ref=f"method:{method_id}",
        slug=method_id,
        title=str(meta.get("name") or meta.get("title") or method_id),
        description=str(meta.get("description") or ""),
        status=str(meta.get("status") or ""),
        body=body,
        path=str(md_path),
        version=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def _match_stem(directory: Path, token: str) -> Path:
    """精确 stem 命中 → 唯一子串命中；多义/无命中抛 FileNotFoundError。"""
    if not directory.is_dir():
        raise FileNotFoundError(f"目录不存在: {directory}")
    files = sorted(directory.glob("*.md"))
    exact = directory / f"{token}.md"
    if exact.is_file():
        return exact
    lowered = token.lower()
    candidates = [
        p for p in files if lowered in p.name.removesuffix(".md").lower()
    ]
    if not candidates:
        raise FileNotFoundError(f"未找到匹配的知识卡: {token!r} (in {directory})")
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates[:8])
        raise ValueError(f"ref {token!r} 匹配多张卡,请用完整 id: {names}")
    return candidates[0]


def _match_method_dir(candidates: list[Path], token: str) -> Path:
    lowered = token.lower()
    exact = [p for p in candidates if p.parent.name.lower() == lowered]
    if exact:
        return exact[0]
    fuzzy = [p for p in candidates if lowered in p.parent.name.lower()]
    if not fuzzy:
        raise FileNotFoundError(f"未找到匹配的方法卡: method:{token}")
    if len(fuzzy) > 1:
        names = ", ".join(p.parent.name for p in fuzzy[:8])
        raise ValueError(f"ref method:{token} 匹配多张卡,请用完整 id: {names}")
    return fuzzy[0]


def find_card(root: Path, ref: str) -> CardInfo:
    """按 ref 解析知识卡。experience:<id或slug> / method:<id>。

    方法卡 runtime 目录（data/methods）优先于 seed 目录（methods），
    与 MethodStore._iter_paths 的 "Runtime copy wins" 口径一致。
    """
    root = Path(root)
    text = str(ref or "").strip()
    if text.lower().startswith("experience:"):
        token = text[len("experience:") :].removesuffix(".md").strip()
        return load_experience_card(_match_stem(root / "experiences", token))
    if text.lower().startswith("method:"):
        token = text[len("method:") :].strip()
        candidates: list[Path] = []
        for base in (root / "data" / "methods", root / "methods"):
            if base.is_dir():
                candidates.extend(sorted(base.glob("*/METHOD.md")))
        if not candidates:
            raise FileNotFoundError("方法卡目录不存在或为空")
        return load_method_card(_match_method_dir(candidates, token))
    raise ValueError(f"ref 必须以 experience: 或 method: 开头: {ref!r}")


def card_summary_lines(card: CardInfo) -> list[str]:
    """state 第二段：卡片要点（区分经验卡/方法卡字段集）。"""
    if card.kind == "method":
        essence = card.description or _clip(card.body, _FIELD_LIMIT)
        return [f"使用的方法条目: 「{card.title}」——{essence}（状态: {card.status or '未知'}）"]
    parts = [f"「{card.title}」"]
    if card.scenario:
        parts.append(f"适用场景: {_clip(card.scenario)}")
    if card.root_cause:
        parts.append(f"根因认识: {_clip(card.root_cause)}")
    if card.solution:
        parts.append(f"解决方案: {_clip(card.solution)}")
    if card.evidence:
        parts.append(f"验证证据: {_clip(card.evidence)}")
    if card.tags:
        parts.append(f"标签: {', '.join(card.tags[:8])}")
    kind_zh = "教训" if card.record_kind == "lesson" else "经验"
    return [
        f"使用的{kind_zh}条目: " + "；".join(parts)
        + f"（状态: {card.status or '未知'}）"
    ]


def use_decision_reported(use_entry: dict) -> str:
    """使用回执里的 decision（经验侧字段名为 use_decision）。"""
    return str(
        use_entry.get("decision")
        or use_entry.get("use_decision")
        or ""
    ).strip()


def build_state(card: CardInfo, use_entry: dict) -> str:
    """三段式中文 state：任务背景 → 卡片要点 → 实际使用结果。"""
    work_unit = str(
        use_entry.get("work_unit_id")
        or use_entry.get("episode_ref")
        or use_entry.get("session_id")
        or ""
    ).strip()
    ts = str(use_entry.get("ts") or "").strip()
    binding = str(use_entry.get("work_unit_binding") or "").strip()
    task_line = "任务: "
    if work_unit:
        task_line += f"工作单元 {work_unit}"
        if binding and binding != "explicit":
            task_line += f"（归属方式 {binding}）"
    else:
        task_line += "归属不明的使用回执（无工作单元绑定）"
    if ts:
        task_line += f"，使用回执提交于 {ts}"
    task_line += "。执行方在任务收尾时提交了该条目的使用声明，第三段是其使用结果自述。"

    decision = use_decision_reported(use_entry)
    decision_zh = _DECISION_ZH.get(decision, decision or "未声明")
    benefit = str(use_entry.get("benefit") or "unknown").strip().lower()
    benefit_zh = _BENEFIT_ZH.get(benefit, benefit)
    note = _clip(use_entry.get("note") or "", _NOTE_LIMIT)
    suggestion = _clip(use_entry.get("suggestion") or "")
    evidence_refs = [
        str(v) for v in (use_entry.get("evidence_refs") or []) if str(v).strip()
    ]
    evidence_level = str(use_entry.get("evidence_level") or "").strip()

    result_parts = [f"执行方声明: {decision_zh}；自评收益: {benefit_zh}"]
    if evidence_level:
        result_parts.append(f"自评证据级别: {evidence_level}")
    if note:
        result_parts.append(f"过程说明: {note}")
    if evidence_refs:
        shown = "; ".join(evidence_refs[:3]) + (" 等" if len(evidence_refs) > 3 else "")
        result_parts.append(f"证据引用: {shown}")
    if suggestion:
        result_parts.append(f"执行方建议: {suggestion}")
    result_line = "实际使用结果: " + "。".join(result_parts) + "。"

    state = "\n".join([task_line, *card_summary_lines(card), result_line])
    if len(state) > _STATE_LIMIT:
        state = state[: _STATE_LIMIT - 1] + "…"
    return state
