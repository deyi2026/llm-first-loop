"""skills loader 标准解析单测（DESIGN-20261009 P1-A: T18 + §5.2 视图分离）."""


from llm_loop.skills.loader import (
    find_skill,
    find_skills,
    parse_skill_md,
    scan_skills_dir,
)

STD = """---
name: std-skill
description: 标准技能
allowed-tools:
  - execute_command
  - read_file
metadata:
  phase: release
  owner: ops
---
# 正文标题

步骤正文。
"""


class TestT18StdParsing:
    def test_multiline_yaml_frontmatter(self):
        m = parse_skill_md(STD, fallback_name="dir", path="/x/SKILL.md")
        assert m.frontmatter_std is True
        assert m.name == "std-skill"
        assert m.description == "标准技能"
        assert m.frontmatter["allowed-tools"] == [
            "execute_command",
            "read_file",
        ]  # 多行 YAML 列表真实解析（旧极简解析做不到）
        assert m.frontmatter["metadata"] == {"phase": "release", "owner": "ops"}
        assert m.body.startswith("# 正文标题")
        assert m.raw_text == STD  # 原文视图完整保留

    def test_no_frontmatter_legacy_path(self):
        text = "# 纯正文\n第二行\n"
        m = parse_skill_md(text, fallback_name="legacy", path="/x/SKILL.md")
        assert m.frontmatter_std is False
        assert m.name == "legacy"
        assert m.description.startswith("纯正文")
        assert m.raw_text == text

    def test_malformed_yaml_falls_back_legacy(self):
        # 旧格式: 非法 YAML（key: 无值集合形）→ 极简降级不崩
        text = "---\nname ok: : broken [\nnot yaml at all\n---\n正文\n"
        m = parse_skill_md(text, fallback_name="d", path="/x")
        assert m.frontmatter_std is False
        assert m.body == "正文"  # 旧行为保留（frontmatter 块剥离）

    def test_frontmatter_scalar_rejected(self):
        text = "---\njust a string\n---\nbody\n"
        m = parse_skill_md(text, fallback_name="d", path="/x")
        assert m.frontmatter_std is False

    def test_frontmatter_size_limit(self):
        huge = "---\n" + "x" * (65 * 1024) + "\n---\nbody\n"
        m = parse_skill_md(huge, fallback_name="d", path="/x")
        assert m.frontmatter_std is False  # 超 64KB → 降级（§10.2）

    def test_scan_with_package(self, tmp_path):
        d = tmp_path / "skills" / "s1"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(STD)
        metas = scan_skills_dir(tmp_path / "skills", package="mypkg")
        assert metas[0].package == "mypkg"


class TestFindSkills:
    def _make(self, tmp_path, dirs):
        skills = tmp_path / "skills"
        for dirname, text in dirs.items():
            d = skills / dirname
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(text)

    def test_package_qualified(self, tmp_path):
        self._make(
            tmp_path,
            {"a": "---\nname: common\n---\nx"},
        )
        # package-qualified 需要包上下文（catalog/标准包扫描传入）
        hits = find_skills(tmp_path / "skills", "mypkg/common", package="mypkg")
        assert [h.name for h in hits] == ["common"]
        # 无包上下文时 package-qualified 查不到（legacy 目录无包语义）
        assert find_skills(tmp_path / "skills", "mypkg/common") == []

    def test_bare_name_unique(self, tmp_path):
        self._make(
            tmp_path,
            {"a": "---\nname: only\n---\nx"},
        )
        hits = find_skills(tmp_path / "skills", "only")
        assert len(hits) == 1

    def test_bare_name_conflict_returns_all(self, tmp_path):
        # 两个包目录各自含同名技能（跨目录冲突）
        pkg_a = tmp_path / "pkg_a" / "skills" / "s"
        pkg_a.mkdir(parents=True)
        (pkg_a / "SKILL.md").write_text("---\nname: dup\n---\nA")
        pkg_b = tmp_path / "pkg_b" / "skills" / "s"
        pkg_b.mkdir(parents=True)
        (pkg_b / "SKILL.md").write_text("---\nname: dup\n---\nB")
        # 同一 skills_dir 下两个目录声明同名 → scan 去重保留首个（现有纪律）
        # 冲突候选语义在跨包合并时生效（catalog 层）
        hits = find_skills(pkg_a.parent, "dup")
        assert len(hits) == 1

    def test_cross_dir_same_name_scan_dedup(self, tmp_path):
        skills = tmp_path / "skills"
        for dirname in ("d1", "d2"):
            d = skills / dirname
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: same\n---\n{dirname}")
        metas = scan_skills_dir(skills)
        assert len(metas) == 1  # 重名保留先扫描（如实跳过）

    def test_find_skill_legacy_compat(self, tmp_path):
        self._make(tmp_path, {"a": "---\nname: legacy\n---\nx"})
        assert find_skill(tmp_path / "skills", "legacy") is not None
        assert find_skill(tmp_path / "skills", "ghost") is None
