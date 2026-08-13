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

    def to_md(self) -> str:
        """序列化为 YAML front matter + Markdown body。"""
        lines = ["---"]
        lines.append(f"title: {_yaml_str(self.title)}")
        lines.append(f"scenario: {_yaml_str(self.scenario)}")
        lines.append(f"root_cause: {_yaml_str(self.root_cause)}")
        lines.append(f"solution: {_yaml_str(self.solution)}")
        lines.append(f"evidence: {_yaml_str(self.evidence)}")
        lines.append(f"tags: [{', '.join(_yaml_str(t) for t in self.tags)}]")
        if self.source:
            lines.append("source:")
            for k, v in self.source.items():
                lines.append(f"  {k}: {_yaml_str(str(v))}")
        else:
            lines.append("source: {}")
        lines.append(f"status: {self.status}")
        lines.append(f"created_at: {_yaml_str(self.created_at)}")
        lines.append(f"updated_at: {_yaml_str(self.updated_at)}")
        lines.append("---")
        if self.body:
            lines.append("")
            lines.append(self.body)
        return "\n".join(lines)

    @classmethod
    def from_md(cls, content: str) -> ExperienceDocument:
        """解析 YAML front matter 还原对象；失败抛 ExperienceParseError。"""
        fields_map = _parse_front_matter(content)
        body = _extract_body(content)
        return cls(
            title=str(fields_map.get("title", "")),
            scenario=str(fields_map.get("scenario", "")),
            root_cause=str(fields_map.get("root_cause", "")),
            solution=str(fields_map.get("solution", "")),
            evidence=str(fields_map.get("evidence", "")),
            tags=list(fields_map.get("tags", [])),
            source=dict(fields_map.get("source", {})),
            status=str(fields_map.get("status", "active")),
            created_at=str(fields_map.get("created_at", "")),
            updated_at=str(fields_map.get("updated_at", "")),
            body=body,
        )


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
        if val:
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
