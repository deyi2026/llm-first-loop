"""Installation briefing: the stable runtime index loaded into the context prefix.

A fresh install knows the model endpoint but not what the installation carries.
This module turns the on-disk resources into a small, byte-stable index of
rules, experience and tools/skills.  It is intentionally an index, not a
mirror: full rule text and experience bodies stay in their authoritative files
and are read on demand.

The output is pure data derived from local paths.  It contains no credentials,
no user content and no mutable counters that change between prompts unless the
underlying resources actually changed.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from llm_loop.core.prompt import INSTALLATION_INDEX_HEADING

_MAX_RULES = 12
_MAX_METHODS = 8
_MAX_SKILLS = 12
_CORE_RULE_IDS = (
    "RULE-AI-00", "RULE-AI-01", "RULE-AI-02", "RULE-AI-07",
    "RULE-AI-08", "RULE-AI-18", "RULE-AI-23", "RULE-AI-24",
)
_RULE_RE = re.compile(r"^##\s+[^：\n]*：(.*?)（(RULE-AI-\d+)", re.MULTILINE)

_CACHE: dict[str, str] = {}


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else default


def _root() -> Path:
    raw = os.environ.get("LFL_RUNTIME_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser()
    # Source layout: <repo>/src/llm_loop/runtime/briefing.py
    # Bundle layout: <bundle>/llm_loop/runtime/briefing.py
    candidate = Path(__file__).resolve().parents[2]
    return candidate.parent if candidate.name == "src" else candidate


def _rule_index(docs_dir: Path) -> list[str]:
    path = docs_dir / "ai_rules.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    found: dict[str, str] = {}
    for title, rule_id in _RULE_RE.findall(text):
        label = " ".join(title.split())
        if rule_id not in found and label:
            found[rule_id] = label
    ordered = [rid for rid in _CORE_RULE_IDS if rid in found]
    if not ordered:
        ordered = sorted(found)[:6]
    return [f"- {rid} {found[rid]}" for rid in ordered[:_MAX_RULES]]


def _method_index(methods_dir: Path) -> tuple[int, list[str]]:
    try:
        entries = sorted(p for p in methods_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return (0, [])
    names = []
    for entry in entries:
        spec = entry / "METHOD.md"
        title = ""
        try:
            head = spec.read_text(encoding="utf-8")[:2000]
        except OSError:
            head = ""
        match = re.search(r"^name:\s*(.+)$", head, re.MULTILINE)
        if match:
            title = match.group(1).strip()
        names.append(title or entry.name)
    return (len(entries), names)


def _count_files(directory: Path, pattern: str) -> int:
    try:
        return sum(1 for p in directory.iterdir() if p.is_file() and p.suffix == pattern)
    except OSError:
        return 0


def _skill_index(skills_dir: Path) -> tuple[int, list[str]]:
    try:
        entries = sorted(p.name for p in skills_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return (0, [])
    return (len(entries), entries)


def _signature(*paths: Path) -> str:
    parts = [str(p) for p in paths]
    for path in paths:
        try:
            parts.append(str(path.stat().st_mtime_ns))
        except OSError:
            parts.append("missing")
    return "|".join(parts)


def _paths() -> dict[str, Path]:
    code = _root()
    data = _env_path("DATA_DIR", code / "data")
    state = data.parent if data.name == "data" else data
    return {
        "docs": _env_path("DOCS_DIR", code / "docs"),
        "methods": _env_path("METHOD_SEED_DIR", code / "methods"),
        "experiences": _env_path("EXPERIENCES_DIR", state / "experiences"),
        "skills": _env_path("SKILLS_DIR", code / "skills"),
    }


def inspect_installation_assets(overrides: Mapping[str, str] | None = None) -> dict[str, int]:
    """Count the three asset classes the briefing would load (read-only).

    ``overrides`` lets the read-only doctor use the same paths the runtime would
    bind from configuration (docs/methods/experiences/skills) without mutating
    the process environment.
    """

    paths = _paths()
    for key in ("docs", "methods", "experiences", "skills"):
        raw = str((overrides or {}).get(key, "") or "").strip()
        if raw:
            paths[key] = Path(raw).expanduser()
    methods, _names = _method_index(paths["methods"])
    return {
        "rules": len(_rule_index(paths["docs"])),
        "methods": methods,
        "experiences": _count_files(paths["experiences"], ".md"),
        "skills": _skill_index(paths["skills"])[0],
    }


def build_installation_briefing() -> str:
    """Return a bounded, deterministic installation index (empty on failure)."""

    paths = _paths()
    docs_dir = paths["docs"]
    methods_dir = paths["methods"]
    experiences_dir = paths["experiences"]
    skills_dir = paths["skills"]
    signature = _signature(docs_dir, methods_dir, experiences_dir, skills_dir)
    # Directory mtimes do not change when a file's content changes; include the
    # one file whose contents feed the index.
    try:
        signature += "|rules:" + str((docs_dir / "ai_rules.md").stat().st_mtime_ns)
    except OSError:
        signature += "|rules:missing"
    if _CACHE.get("signature") == signature:
        return _CACHE.get("text", "")

    rules = _rule_index(docs_dir)
    method_count, method_names = _method_index(methods_dir)
    experience_count = _count_files(experiences_dir, ".md")
    skill_count, skill_names = _skill_index(skills_dir)

    lines = [INSTALLATION_INDEX_HEADING, ""]
    lines.append("### 规则")
    if rules:
        lines.append("长期约束（完整真值源：docs/ai_rules.md，需要时读取）：")
        lines.extend(rules)
    else:
        lines.append("规则真值源：docs/ai_rules.md（当前安装未找到，按 SOUL 与通用核心认知执行）。")

    lines += ["", "### 经验"]
    if method_count or experience_count:
        pieces = []
        if method_count:
            pieces.append(f"方法 {method_count} 条")
        if experience_count:
            pieces.append(f"经验 {experience_count} 条")
        lines.append("本安装已有" + "、".join(pieces) + "。任务相关时用 "
                     "search_records(kind=method|experience|lesson, query=任务词) 检索；"
                     "命中后按返回的 stable ref 精确水合，不凭标题猜内容。")
        if method_names:
            lines.append("方法索引：" + "、".join(method_names[:_MAX_METHODS]))
    else:
        lines.append("经验库当前为空。用 search_records 检索；没有命中就按通用推理执行，"
                     "完成后可用 save_experience 沉淀可复用结论。")

    lines += ["", "### 工具与技能"]
    lines.append("工具参数以 API schema 为真值；陌生工具先 get_tool_schema，不猜参数。"
                 "常用类别：文件读写、代码/内容搜索、命令执行、浏览器感知与操作、"
                 "证据/记录检索、任务与子代理。技能用 skill_list 发现、skill_load 加载。")
    if skill_count:
        lines.append(f"已安装技能 {skill_count} 个：" + "、".join(skill_names[:_MAX_SKILLS]) +
                     ("…" if skill_count > _MAX_SKILLS else ""))

    text = "\n".join(lines).strip()
    if len(text) > 4000:
        text = text[:3900].rstrip() + "\n…（索引已截断，完整内容见对应文件）"
    _CACHE["signature"] = signature
    _CACHE["text"] = text
    return text
