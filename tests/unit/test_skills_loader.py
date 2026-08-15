"""B3(2026-08-14) 插件化 Skill 加载测试（零 LLM 零网络）.

覆盖: frontmatter 解析（name/description/缺省 fallback/非法忽略）/ 目录扫描
（一层子目录/无 SKILL.md 跳过/损坏 fail-open/重名去重）/ skill_list 与 skill_load
工具执行（空目录/按名加载/未知名如实报错/缺参）/ factory 装配注入（skills_dir）。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.skills.loader import find_skill, parse_skill_md, scan_skills_dir

_SKILL_TEMPLATE = """---
name: {name}
description: {desc}
---
# {title}

正文步骤:
1. 第一步
2. 第二步
"""


def _mk_skill(root: Path, dir_name: str, name: str, desc: str) -> Path:
    d = root / dir_name
    d.mkdir(parents=True, exist_ok=True)
    f = d / "SKILL.md"
    f.write_text(
        _SKILL_TEMPLATE.format(name=name, desc=desc, title=name), encoding="utf-8"
    )
    return f


# ── parse_skill_md ──


def test_parse_frontmatter():
    meta = parse_skill_md(
        _SKILL_TEMPLATE.format(name="deploy", desc="部署流程", title="deploy"),
        "x",
        "/p/SKILL.md",
    )
    assert meta.name == "deploy"
    assert meta.description == "部署流程"
    assert "正文步骤" in meta.body
    assert "---" not in meta.body  # frontmatter 已剥离


def test_parse_no_frontmatter_falls_back():
    meta = parse_skill_md("# 无 frontmatter 技能\n\n正文", "dirname", "/p/SKILL.md")
    assert meta.name == "dirname"  # 目录名 fallback
    assert meta.description.startswith("无 frontmatter 技能")  # 正文首行 fallback


def test_parse_malformed_frontmatter():
    """frontmatter 内容非法（无 key: value）→ 整体按正文处理（fail-open）."""
    meta = parse_skill_md("---\nnot yaml at all\n---\n正文", "d", "/p/SKILL.md")
    assert meta.name == "d"
    assert meta.body  # 正文仍在


# ── scan_skills_dir ──


def test_scan_empty_and_missing(tmp_path):
    assert scan_skills_dir(None) == []
    assert scan_skills_dir(tmp_path / "nope") == []


def test_scan_one_level(tmp_path):
    _mk_skill(tmp_path, "deploy", "deploy", "部署流程")
    _mk_skill(tmp_path, "review", "review", "审查清单")
    metas = scan_skills_dir(tmp_path)
    assert [m.name for m in metas] == ["deploy", "review"]  # 目录序稳定
    assert metas[0].path.endswith("SKILL.md")


def test_scan_skips_without_skill_file(tmp_path):
    _mk_skill(tmp_path, "a", "a", "A")
    (tmp_path / "nofile").mkdir()
    metas = scan_skills_dir(tmp_path)
    assert [m.name for m in metas] == ["a"]


def test_scan_corrupt_file_fail_open(tmp_path):
    _mk_skill(tmp_path, "a", "a", "A")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_bytes(b"\xff\xfe\x00 broken utf8")  # 非法 UTF-8 → 读取失败
    metas = scan_skills_dir(tmp_path)
    assert [m.name for m in metas] == ["a"]  # bad 未崩，正常技能仍列出


def test_scan_duplicate_name_dedup(tmp_path):
    _mk_skill(tmp_path, "x1", "same", "X1")
    _mk_skill(tmp_path, "x2", "same", "X2")
    metas = scan_skills_dir(tmp_path)
    assert len(metas) == 1  # 重名保留先扫描到
    assert metas[0].description == "X1"


def test_find_skill(tmp_path):
    _mk_skill(tmp_path, "deploy", "deploy", "部署")
    assert find_skill(tmp_path, "deploy") is not None
    assert find_skill(tmp_path, "missing") is None


# ── 工具执行（skill_list / skill_load）──


class _FakeHost:
    def __init__(self, skills_dir: str | None) -> None:
        self.skills_dir = skills_dir


def test_skill_list_empty(tmp_path):
    from llm_loop.introspection.tools_skill_files import run_skill_list

    r = run_skill_list(_FakeHost(None), {})
    assert r.status.value == "success"
    assert "无外部技能" in r.content


def test_skill_list_lists(tmp_path):
    from llm_loop.introspection.tools_skill_files import run_skill_list

    _mk_skill(tmp_path, "deploy", "deploy", "部署流程")
    r = run_skill_list(_FakeHost(str(tmp_path)), {})
    assert r.status.value == "success"
    assert "deploy" in r.content
    assert "部署流程" in r.content


def test_skill_load_returns_full(tmp_path):
    from llm_loop.introspection.tools_skill_files import run_skill_load

    _mk_skill(tmp_path, "deploy", "deploy", "部署流程")
    r = run_skill_load(_FakeHost(str(tmp_path)), {"name": "deploy"})
    assert r.status.value == "success"
    assert "部署流程" in r.content
    assert "正文步骤" in r.content  # 全文加载


def test_skill_load_unknown_and_missing_param(tmp_path):
    from llm_loop.introspection.tools_skill_files import run_skill_load

    _mk_skill(tmp_path, "deploy", "deploy", "部署")
    r = run_skill_load(_FakeHost(str(tmp_path)), {"name": "nope"})
    assert r.status.value == "failure"
    assert "技能不存在" in r.content
    assert "deploy" in r.content  # 列出可用技能
    r2 = run_skill_load(_FakeHost(str(tmp_path)), {})
    assert r2.status.value == "failure"
    assert "参数错误" in r2.content


# ── factory 装配（skills_dir 注入）──


def test_factory_injects_skills_dir(tmp_path, monkeypatch):
    """build_engine 装配后 skill_list 工具可见且使用注入的目录."""
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    skills = tmp_path / "skills"
    _mk_skill(skills, "ops", "ops", "运维流程")
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        skills_dir=str(skills),
        extract_enabled=False,
        summary_mode="off",
    )
    engine = build_engine(settings)  # type: ignore[arg-type]
    r = engine.corrections.execute("skill_list", {})
    assert r.status.value == "success"
    assert "ops" in r.content
    r2 = engine.corrections.execute("skill_load", {"name": "ops"})
    assert r2.status.value == "success"
    assert "运维流程" in r2.content


def test_factory_default_skills_dir_zero_behavior(tmp_path):
    """skills_dir 指向不存在目录 → skill_list 空清单零行为."""
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        skills_dir=str(tmp_path / "no_such_skills"),
        extract_enabled=False,
        summary_mode="off",
    )
    engine = build_engine(settings)  # type: ignore[arg-type]
    r = engine.corrections.execute("skill_list", {})
    assert r.status.value == "success"
    assert "无外部技能" in r.content


def test_repo_bundled_skills_discoverable(tmp_path, monkeypatch):
    """端到端: 仓库自带 skills/ 示例技能可被真实装配发现并加载（B3 可演示性）.

    用仓库根 skills/ 目录（notebook-session + incident-report 示例 SKILL 入库），
    经 build_engine 真实装配 → skill_list 发现 → skill_load 全文加载。
    """
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    repo_skills = Path(__file__).resolve().parents[2] / "skills"
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        skills_dir=str(repo_skills),
        extract_enabled=False,
        summary_mode="off",
    )
    engine = build_engine(settings)  # type: ignore[arg-type]

    listed = engine.corrections.execute("skill_list", {})
    assert listed.status.value == "success"
    assert "notebook-session" in listed.content
    assert "incident-report" in listed.content

    loaded = engine.corrections.execute("skill_load", {"name": "notebook-session"})
    assert loaded.status.value == "success"
    assert "笔记本会话运维" in loaded.content  # frontmatter 描述
    assert "标准流程" in loaded.content  # 正文全文

    loaded2 = engine.corrections.execute("skill_load", {"name": "incident-report"})
    assert loaded2.status.value == "success"
    assert "故障报告撰写" in loaded2.content


def test_repo_bundled_skills_have_valid_frontmatter():
    """入库示例 SKILL 格式自检: 每个 SKILL.md 可解析、name 与目录名一致（防手误）."""
    repo_skills = Path(__file__).resolve().parents[2] / "skills"
    metas = scan_skills_dir(repo_skills)
    names = {m.name for m in metas}
    assert {"notebook-session", "incident-report"} <= names
    for meta in metas:
        assert meta.description, f"{meta.name} 缺 description"
        assert meta.body, f"{meta.name} 正文为空"
