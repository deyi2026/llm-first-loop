"""插件化 Skill 加载器（B3，2026-08-14；P1-A 标准解析升级，DESIGN-20261009 §5.2）.

外部 `skills/` 目录（Claude Code 风格）自动扫描加载：
    skills/<skill_name>/SKILL.md
    SKILL.md 格式: YAML frontmatter（--- 块，多行标准 YAML）+ 正文 markdown。

机制:
- scan_skills_dir: 启动/首次调用时扫描一层子目录（skills/*/SKILL.md）
- parse_skill_md: 标准 YAML frontmatter 解析（safe loader）；
  无 frontmatter → legacy 路径（目录名 + 正文首行 fallback，T18 兼容）；
  frontmatter 非法 YAML → 极简 key:value 降级（fail-open，旧行为保留）
- 原文视图与解析视图分开（§5.2）: raw_text=原文全文（含 frontmatter，
  skill_load 用）；name/description/body=解析视图（目录展示用）
- find_skills: package-qualified ref（"pkg/skill"）精确匹配；裸名返回全部
  候选（唯一命中可直接解析，多命中由调用方如实报告冲突）
- 损坏/缺 SKILL.md → fail-open 跳过；目录不存在/为空 → 空清单（零回归）

YAML 依赖资格验证（§11.1）: PyYAML safe_load（SafeLoader，禁用任意构造/标签）；
frontmatter 输入 ≤64KB（§10.2 输入大小限制）；yaml 不可用时自动降级极简解析。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SKILL_FILE = "SKILL.md"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_FRONTMATTER_MAX = 64 * 1024  # §10.2 输入大小限制

try:  # §11.1: YAML 依赖资格验证（safe loader；缺失自动降级，不硬崩）
    import yaml

    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover - 环境缺 PyYAML 时降级路径
    yaml = None  # type: ignore[assignment]
    _YAML_AVAILABLE = False


@dataclass(frozen=True)
class SkillMeta:
    """一个外部 Skill 的元数据（frontmatter + 正文，如实解析）."""

    name: str
    description: str
    path: str  # SKILL.md 绝对路径
    body: str = ""  # frontmatter 之后的正文（解析视图）
    frontmatter: dict = field(default_factory=dict)
    package: str | None = None  # P1-A: 所属标准包名（独立技能 None）
    raw_text: str = ""  # P1-A: 原文全文（含 frontmatter；skill_load 原文视图）
    frontmatter_std: bool = False  # P1-A: 标准 YAML 解析成功（False=legacy/降级）


def _legacy_flat_parse(raw: str) -> dict:
    """极简 key: value 解析（legacy 降级；非法行忽略）."""
    fm: dict = {}
    for line in raw.splitlines():
        line = line.strip()
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip().strip("\"'")
            v = v.strip().strip("\"'")
            if k and v:
                fm[k] = v
    return fm


def _parse_frontmatter_yaml(raw: str) -> dict | None:
    """标准 YAML frontmatter 解析（多行支持）.

    返回 dict=解析成功；None=不可解析（调用方降级 legacy 极简，fail-open）。
    仅 safe_load（SafeLoader，禁用任意构造）；超限/异常如实返回 None。
    """
    if not _YAML_AVAILABLE:
        return None
    if len(raw.encode("utf-8", errors="ignore")) > _FRONTMATTER_MAX:
        return None
    try:
        data = yaml.safe_load(raw)  # type: ignore[union-attr]
    except yaml.YAMLError:  # type: ignore[union-attr]
        return None
    if data is None:
        return {}
    if not isinstance(data, dict):
        return None  # frontmatter 必须是映射（标量/列表 → 降级）
    return data


def parse_skill_md(
    text: str,
    fallback_name: str,
    path: str,
    *,
    package: str | None = None,
) -> SkillMeta:
    """解析 SKILL.md（frontmatter name/description + 正文）.

    - 标准 YAML frontmatter（多行）优先；成功 → frontmatter_std=True
    - frontmatter 非法 YAML → 极简 key:value 降级（fail-open，旧兼容）
    - 无 frontmatter → name 用目录名，description 用正文首行（legacy，T18）
    """
    body = text
    fm: dict = {}
    std = False
    m = _FRONTMATTER_RE.match(text)
    if m:
        raw = m.group(1)
        parsed = _parse_frontmatter_yaml(raw)
        if parsed is not None:
            fm = parsed
            std = True
        else:
            fm = _legacy_flat_parse(raw)
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
        package=package,
        raw_text=text,
        frontmatter_std=std,
    )


def scan_skills_dir(
    skills_dir: str | Path | None,
    *,
    package: str | None = None,
) -> list[SkillMeta]:
    """扫描 `skills_dir/*/SKILL.md`（一层子目录）.

    目录不存在/为空 → []（零行为）；单个 SKILL.md 损坏 → 跳过（fail-open）。
    名称冲突（两个目录同名 skill）→ 保留先扫描到的，后者如实跳过。
    package: 标准包技能扫描时传入包名（package-qualified ref 用，P1-A）。
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
        meta = parse_skill_md(
            text, fallback_name=sub.name, path=str(skill_file), package=package
        )
        if meta.name in seen:
            continue  # 重名冲突：保留先扫描到（如实跳过）
        seen.add(meta.name)
        out.append(meta)
    return out


def find_skills(
    skills_dir: str | Path | None,
    name: str,
    *,
    package: str | None = None,
) -> list[SkillMeta]:
    """按名定位（P1-A，§5.2）: package-qualified（"pkg/skill"）精确；裸名返回全部候选.

    - package: 扫描时的包上下文（标准包技能扫描传入；legacy 目录 None）
    - "pkg/skill" → 该包内精确匹配（package 不符的候选不参与）
    - 裸名 → 所有同名候选：唯一命中=单元素（可直接解析）；多命中=全部候选
      （调用方如实报告冲突，不静默择一）；空=未找到
    """
    metas = scan_skills_dir(skills_dir, package=package)
    if "/" in name:
        pkg, _, short = name.partition("/")
        if not pkg or not short:
            return []
        return [m for m in metas if (m.package or "") == pkg and m.name == short]
    return [m for m in metas if m.name == name]


def find_skill(skills_dir: str | Path | None, name: str) -> SkillMeta | None:
    """按名定位（legacy 兼容）；未找到返回 None（调用方如实报错）."""
    hits = find_skills(skills_dir, name)
    return hits[0] if hits else None
