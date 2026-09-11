"""经验文档数据模型与极简 YAML front matter 解析器（design §2.3.2.5/§2.4.3）.

不引入 PyYAML 依赖，仅支持经验库所需扁平 key: value / key: [list] / key: 缩进块。
解析失败抛 ExperienceParseError（调用方捕获如实标注，fail-open）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class ExperienceParseError(Exception):
    """经验文档解析失败（front matter 格式非法）。"""


@dataclass
class ExperienceDocument:
    """经验文档数据模型（spec 6.1 字段 1-11）。"""

    title: str
    scenario: str
    root_cause: str
    solution: str
    evidence: str
    tags: list[str]
    source: dict
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    body: str = ""
    superseded_by: str = ""
    promoted_to_rule: str = ""
    last_verified_at: str = ""
    # P1-B: positive reusable experience and negative/failed lesson are distinct facts.
    # Legacy documents deliberately remain readable without being silently promoted to
    # "verified" merely because they predate these fields.
    record_kind: str = "experience"
    verification_state: str = "legacy_unclassified"

    def to_md(self) -> str:
        """序列化为 YAML front matter + Markdown body。"""
        lines = ["---"]
        _append_scalar(lines, "title", self.title)
        _append_scalar(lines, "scenario", self.scenario)
        _append_scalar(lines, "root_cause", self.root_cause)
        _append_scalar(lines, "solution", self.solution)
        _append_scalar(lines, "evidence", self.evidence)
        lines.append(f"tags: [{', '.join(_yaml_str(t) for t in self.tags)}]")
        if self.source:
            if set(self.source.keys()) == {"raw"} and "\n" in str(self.source["raw"]):
                raise ValueError(
                    "source 降级形态 raw 值含换行，破坏单行不变量，拒绝写入（防静默改写，design D15）"
                )
            lines.append("source:")
            for k, v in self.source.items():
                lines.append(f"  {k}: {_yaml_str(str(v))}")
        else:
            lines.append("source: {}")
        _append_scalar(lines, "status", self.status)
        _append_scalar(lines, "record_kind", self.record_kind)
        _append_scalar(lines, "verification_state", self.verification_state)
        _append_scalar(lines, "created_at", self.created_at)
        _append_scalar(lines, "updated_at", self.updated_at)
        if self.superseded_by:
            _append_scalar(lines, "superseded_by", self.superseded_by)
        if self.promoted_to_rule:
            _append_scalar(lines, "promoted_to_rule", self.promoted_to_rule)
        if self.last_verified_at:
            _append_scalar(lines, "last_verified_at", self.last_verified_at)
        lines.append("---")
        if self.body:
            lines.append("")
            lines.append(self.body)
        return "\n".join(lines)

    @classmethod
    def from_md(cls, content: str) -> ExperienceDocument:
        """解析 YAML front matter 还原对象；失败唯一异常形态 ExperienceParseError。

        source 字段非法形态（标量/内联 JSON 等）宽容降级为 {"raw": "<原值>"}，不判死文档
        （可降级文档态）；其余任何内部异常转译为 ExperienceParseError，不裸逃逸。
        """
        try:
            fields_map = _parse_front_matter(content)
            body = _extract_body(content)
            return cls(
                title=str(fields_map.get("title", "")),
                scenario=str(fields_map.get("scenario", "")),
                root_cause=str(fields_map.get("root_cause", "")),
                solution=str(fields_map.get("solution", "")),
                evidence=str(fields_map.get("evidence", "")),
                tags=list(fields_map.get("tags", [])),
                source=_coerce_mapping(fields_map.get("source", {}), "source"),
                status=str(fields_map.get("status", "active")),
                created_at=str(fields_map.get("created_at", "")),
                updated_at=str(fields_map.get("updated_at", "")),
                body=body,
                superseded_by=str(fields_map.get("superseded_by", "")),
                promoted_to_rule=str(fields_map.get("promoted_to_rule", "")),
                last_verified_at=str(fields_map.get("last_verified_at", "")),
                record_kind=str(fields_map.get("record_kind", "experience")),
                verification_state=str(
                    fields_map.get("verification_state", "legacy_unclassified")
                ),
            )
        except ExperienceParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ExperienceParseError(f"经验文档解析失败({type(exc).__name__}): {exc}") from exc


def _coerce_mapping(value: object, field_name: str) -> dict:
    """映射型字段宽容降级：dict 原样返回，其余形态降级为 {"raw": "<原值文本>"}。

    field_name 供未来映射型字段复用（当前仅 source 调用）；原值文本完整保留（不截断
    不转义），禁止猜测还原内联 JSON——'{"type": "x"}' 字符串只降级 raw，不 parse 回映射。
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return {"raw": value}
    return {"raw": str(value)}


def _yaml_str(val: str) -> str:
    """YAML 字符串序列化：含特殊字符或空则加引号。"""
    if val is None:
        return '""'
    s = str(val)
    if not s:
        return '""'
    if any(c in s for c in (":", "[", "]", '"', "#", "{", "}", ",")) or s[0] in " \t" or s[-1] in " \t":
        return f'"{s.replace(chr(34), chr(92) + chr(34))}"'
    return s


def _append_scalar(lines: list[str], key: str, value: str) -> None:
    """Append one scalar without emitting parser-invalid physical newlines.

    The experience format intentionally uses a tiny YAML subset rather than PyYAML.
    Multiline model-authored fields therefore need one explicit representation shared
    by writer and reader. A ``|`` block preserves the exact text while leaving legacy
    one-line documents byte-semantically unchanged.
    """

    text = str(value or "")
    if "\n" not in text and "\r" not in text:
        lines.append(f"{key}: {_yaml_str(text)}")
        return
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines.append(f"{key}: |")
    lines.extend(f"  {row}" for row in normalized.split("\n"))


def _parse_front_matter(content: str) -> dict:
    """极简 YAML front matter 解析（支持 key: value / key: [list] / key: 缩进块）。"""
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ExperienceParseError("缺少 front matter 起始标记 '---'")
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        raise ExperienceParseError("缺少 front matter 结束标记 '---'")
    fm_lines = lines[1:end_idx]
    result: dict = {}
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        if not line.strip():
            i += 1
            continue
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if not m:
            raise ExperienceParseError(f"front matter 行格式非法: {line!r}")
        key = m.group(1)
        val = m.group(2).strip()
        if val == "|":
            i += 1
            block: list[str] = []
            while i < len(fm_lines) and fm_lines[i].startswith("  "):
                block.append(fm_lines[i][2:])
                i += 1
            result[key] = "\n".join(block)
        elif val:
            result[key] = _parse_value(val)
            i += 1
        else:
            i += 1
            nested: dict = {}
            while i < len(fm_lines) and fm_lines[i].startswith("  "):
                nm = re.match(r"^\s+(\w+):\s*(.*)$", fm_lines[i])
                if not nm:
                    raise ExperienceParseError(f"嵌套块行格式非法: {fm_lines[i]!r}")
                nested[nm.group(1)] = _parse_value(nm.group(2).strip())
                i += 1
            result[key] = nested
    return result


def _parse_value(val: str):
    """解析标量值：列表 [a, b] 或字符串（去引号）。"""
    val = val.strip()
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        items = [item.strip() for item in inner.split(",")]
        return [_strip_quotes(item) for item in items if item]
    if val == "{}":
        return {}
    return _strip_quotes(val)


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('\\"', '"')
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1]
    return s


def _extract_body(content: str) -> str:
    """提取 front matter 之后的正文。"""
    lines = content.split("\n")
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return ""
    body_lines = lines[end_idx + 1 :]
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    return "\n".join(body_lines)
