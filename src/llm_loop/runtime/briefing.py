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

import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from llm_loop.core.prompt import INSTALLATION_INDEX_HEADING
from llm_loop.timekeeping import system_local_now

_MAX_RULES = 12
_MAX_METHODS = 8
_MAX_SKILLS = 12
# D8：知识健康度段 TTL——ledger 最新成功行时间戳距今超过该值即整段省略。
KNOWLEDGE_SCORE_TTL_SECONDS = 7 * 86400
# D8：趋势符号判定容差（|Δ| ≤ 该值视为 →）。
_KNOWLEDGE_TREND_EPSILON = 0.005
# D8：knowledge_score ledger 磁盘契约落点，与 knowledge_score/ledger.py 的
# KnowledgeScoreLedger.for_root 保持同步。kernel 平面按文件契约只读数据、
# 不 import capability 模块（kernel_import_edges 冻结基线只减不增）；
# 口径一致性由 test_briefing_knowledge_health_matches_ledger_read 锁定。
_KNOWLEDGE_LEDGER_REL = ("data", "knowledge_scores", "ledger.jsonl")
_CORE_RULE_IDS = (
    "RULE-AI-00", "RULE-AI-01", "RULE-AI-02", "RULE-AI-07",
    "RULE-AI-08", "RULE-AI-18", "RULE-AI-23", "RULE-AI-24",
)
_RULE_RE = re.compile(r"^##\s+[^：\n]*：(.*?)（(RULE-AI-\d+)", re.MULTILINE)

_CACHE: dict[str, str] = {}


def _root() -> Path:
    # Source layout: <repo>/src/llm_loop/runtime/briefing.py
    # Bundle layout: <bundle>/llm_loop/runtime/briefing.py
    candidate = Path(__file__).resolve().parents[2]
    return candidate.parent if candidate.name == "src" else candidate


def _paths() -> dict[str, Path]:
    # Bindings intentionally reuse runtime/paths.py resolution (no direct env
    # reads here): experiences state-root inference, METHOD_SEED_DIR, SKILLS_DIR
    # and the linked-worktree skill rebind all follow the engine's own truth.
    # The methods key indexes the seed directory — the same key doctor passes
    # as an override.
    from .paths import resolve_runtime_paths

    resolved = resolve_runtime_paths(data_dir=None, code_root=_root())
    return {
        "docs": resolved.docs_dir,
        "methods": resolved.method_seed_dir,
        "experiences": resolved.experiences_dir,
        "skills": resolved.skills_dir,
        "state_root": resolved.state_root,
    }


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


_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _skill_index(skills_dir: Path) -> tuple[int, list[str]]:
    """Count loadable skills: a directory only counts when SKILL.md exists.

    This mirrors what skill_list can actually load, so the index never
    overstates the installation.  Names are filtered to a conservative charset
    before they can enter the context prefix.
    """
    try:
        entries = sorted(
            p.name
            for p in skills_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".") and (p / "SKILL.md").is_file()
        )
    except OSError:
        return (0, [])
    loadable = [name for name in entries if _SKILL_NAME_RE.match(name)]
    return (len(loadable), loadable)


def _signature(*paths: Path) -> str:
    parts = [str(p) for p in paths]
    for path in paths:
        try:
            parts.append(str(path.stat().st_mtime_ns))
        except OSError:
            parts.append("missing")
    return "|".join(parts)


def _knowledge_score_ledger_path(state_root: Path) -> Path:
    return state_root.joinpath(*_KNOWLEDGE_LEDGER_REL)


def _knowledge_health_lines(
    state_root: Path, *, now: datetime | None = None
) -> list[str]:
    """知识健康度段（D8）：ledger 最后两条成功打分行 → 最新分/Δ/趋势.

    数据源：``<state_root>/data/knowledge_scores/ledger.jsonl``（磁盘契约落点，
    与 ``KnowledgeScoreLedger.for_root`` 及 CLI/web 落点一致）。输出仅
    数字与符号，不含任何会话内容/条目文本。整段省略（返回空，不输出标题行）：
    ledger 文件不存在 / 无成功行 / 最新成功行时间戳距今超过
    ``KNOWLEDGE_SCORE_TTL_SECONDS``。读取异常按省略处理（fail-open）。
    """
    path = _knowledge_score_ledger_path(state_root)
    if not path.is_file():
        return []
    scored: list[tuple[float, str]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # torn 尾行：跳过不炸（与恢复扫描同为 fail-open）
                if not isinstance(row, dict):
                    continue
                if str(row.get("error") or ""):
                    continue  # error 行不是成功打分（与 covered_slot_keys 同口径）
                raw_expected = row.get("expected")
                if isinstance(raw_expected, bool) or not isinstance(raw_expected, (int, float)):
                    continue
                scored.append((float(raw_expected), str(row.get("ts") or "")))
    except Exception:  # noqa: BLE001 — 健康度段 fail-open：账本不可读不破坏简报
        return []
    if not scored:
        return []
    latest_score, latest_ts = scored[-1]
    try:
        stamped = datetime.fromisoformat(latest_ts)
    except ValueError:
        return []
    if stamped.tzinfo is None:
        stamped = stamped.astimezone()
    reference = now or system_local_now()
    if (reference - stamped).total_seconds() > KNOWLEDGE_SCORE_TTL_SECONDS:
        return []
    if len(scored) >= 2:
        delta = latest_score - scored[-2][0]
        if delta > _KNOWLEDGE_TREND_EPSILON:
            trend = "↗"
        elif delta < -_KNOWLEDGE_TREND_EPSILON:
            trend = "↘"
        else:
            trend = "→"
        return [f"知识健康度: {latest_score:.2f} ({delta:+.2f} {trend})"]
    return [f"知识健康度: {latest_score:.2f}"]


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
    """Return a bounded, deterministic installation index (empty on failure).

    The cache lives for the process lifetime: the signature keys on directory
    mtimes (plus ai_rules.md's own mtime), so an in-place edit of a METHOD.md
    or experience file shows up in the index on the next process start, not
    mid-run.  That is deliberate — the prefix must stay byte-stable within a
    session to keep hitting the provider's prefix cache.
    """

    paths = _paths()
    docs_dir = paths["docs"]
    methods_dir = paths["methods"]
    experiences_dir = paths["experiences"]
    skills_dir = paths["skills"]
    state_root = paths["state_root"]
    signature = _signature(docs_dir, methods_dir, experiences_dir, skills_dir)
    # Directory mtimes do not change when a file's content changes; include the
    # one file whose contents feed the index.
    try:
        signature += "|rules:" + str((docs_dir / "ai_rules.md").stat().st_mtime_ns)
    except OSError:
        signature += "|rules:missing"
    # D8: 知识健康度段同样由文件内容驱动——ledger mtime 进入签名，新打分行
    # 在下次构建时如实反映（与 ai_rules.md 同一原则）。
    score_ledger_path = _knowledge_score_ledger_path(state_root)
    try:
        signature += "|knowledge:" + str(score_ledger_path.stat().st_mtime_ns)
    except OSError:
        signature += "|knowledge:missing"
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
    lines.append("工具参数以 API schema 为真值；参数语义不明时先读该工具的完整 Schema 再调用，不猜参数。"
                 "常用类别：文件读写、代码/内容搜索、命令执行、浏览器感知与操作、"
                 "证据/记录检索、任务与子代理。技能用 skill_list 发现、skill_load 加载。")
    if skill_count:
        lines.append(f"已安装技能 {skill_count} 个：" + "、".join(skill_names[:_MAX_SKILLS]) +
                     ("…" if skill_count > _MAX_SKILLS else ""))

    # D8：知识健康度段（method/skill 段之后）——ledger 缺失/为空/TTL 过期整段省略。
    health = _knowledge_health_lines(state_root)
    if health:
        lines += ["", "### 知识健康度"]
        lines.extend(health)

    text = "\n".join(lines).strip()
    if len(text) > 4000:
        text = text[:3900].rstrip() + "\n…（索引已截断，完整内容见对应文件）"
    _CACHE["signature"] = signature
    _CACHE["text"] = text
    return text
