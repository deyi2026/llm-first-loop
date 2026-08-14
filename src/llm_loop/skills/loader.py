"""插件化 Skill 加载器（B3，2026-08-14）.

外部 `skills/` 目录（Claude Code 风格）自动扫描加载：
    skills/<skill_name>/SKILL.md
    SKILL.md 格式: 可选 YAML frontmatter（--- 块含 name/description）+ 正文 markdown。

机制:
- scan_skills_dir: 启动/首次调用时扫描一层子目录（skills/*/SKILL.md）
- parse_skill_md: frontmatter 解析（name/description 缺省 fallback 文件名/正文首行）
- 损坏/缺 SKILL.md/frontmatter 非法 → fail-open 跳过（如实不阻断）
- skill_load 按名返回 SKILL.md 全文（AI 加载进上下文执行）
- 目录不存在/为空 → 空清单（零行为零回归）

零依赖（仅标准库），纯函数可测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SKILL_FILE = "SKILL.md"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class SkillMeta:
    """一个外部 Skill 的元数据（frontmatter + 正文，如实解析）."""

    name: str
    description: str
    path: str  # SKILL.md 绝对路径
    body: str = ""  # frontmatter 之后的正文（skill_load 返回全文含 frontmatter）
    frontmatter: dict = field(default_factory=dict)


def parse_skill_md(text: str, fallback_name: str, path: str) -> SkillMeta:
    """解析 SKILL.md（frontmatter name/description + 正文）.

    - 无 frontmatter → name 用目录名，description 用正文首行（如实 fallback）
    - frontmatter 非 YAML（无法解析）→ 整体视为正文（fail-open）
    """
    body = text
    fm: dict = {}
    m = _FRONTMATTER_RE.match(text)
    if m:
        raw = m.group(1)
        # 极简 key: value 解析（name/description/frontmatter 常用形态；非法行忽略）
        for line in raw.splitlines():
            line = line.strip()
            if ":" in line:
                k, _, v = line.partition(":")
                k = k.strip().strip('"\'')
                v = v.strip().strip('"\'')
                if k and v:
                    fm[k] = v
        body = text[m.end() :]
    name = str(fm.get("name") or fallback_name).strip()
    description = str(fm.get("description") or "").strip()
    if not description:
        # fallback: 正文首行（去标题符号）
        first = next((line for line in body.splitlines() if line.strip()), "")
        description = first.lstrip("#").strip()[:200]
    return SkillMeta(
        name=name,
        description=description,
        path=path,
        body=body.strip(),
        frontmatter=fm,
    )


def scan_skills_dir(skills_dir: str | Path | None) -> list[SkillMeta]:
    """扫描 `skills_dir/*/SKILL.md`（一层子目录）.

    目录不存在/为空 → []（零行为）；单个 SKILL.md 损坏 → 跳过（fail-open）。
    名称冲突（两个目录同名 skill）→ 保留先扫描到的，后者如实跳过。
    """
    if not skills_dir:
        return []
    root = Path(skills_dir)
    if not root.is_dir():
        return []
    out: list[SkillMeta] = []
    seen: set[str] = set()
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        skill_file = sub / _SKILL_FILE
        if not skill_file.is_file():
            continue
        try:
            text = skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # 读取失败/编码损坏 fail-open 跳过
        meta = parse_skill_md(text, fallback_name=sub.name, path=str(skill_file))
        if meta.name in seen:
            continue  # 重名冲突：保留先扫描到（如实跳过）
        seen.add(meta.name)
        out.append(meta)
    return out


def find_skill(skills_dir: str | Path | None, name: str) -> SkillMeta | None:
    """按名定位（skill_load 用）；未找到返回 None（调用方如实报错）."""
    for meta in scan_skills_dir(skills_dir):
        if meta.name == name:
            return meta
    return None
