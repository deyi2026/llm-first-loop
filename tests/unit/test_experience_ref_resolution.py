"""EVO-20261031-a72df001 回归：等价引用形态必须解析到同一张卡。

真实事故（2026-10-30 / 2026-10-31 两次会话，4 次 record_use 落空）：
  sanitize_slug() 把 slug 截到 50 字符 → 卡片文件名用截断形、卡片 title 保留全文；
  模型按 title 反推 ref → 该 stem 在磁盘上不存在 →
  refine_experience(record_use) 与 search_records 精确水合同时落空，
  回执为"未找到指定经验"。

契约：
  1. 精确文件名 stem 语义不变（既有调用零回归）；
  2. title 全 slug / 截断前缀互含形态 → 解析到唯一 canonical stem；
  3. 多候选 → fail-closed（不静默任选一张卡）；
  4. 未找到 → 回显经验库目录与近邻候选，便于自诊断。
"""

from __future__ import annotations

import re
from pathlib import Path

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.search import RecordSearcher

LONG_TITLE = (
    "git_push 审查资格在并发写者下于 PASS 之后失效："
    "先查远端是否已含目标提交，再决定是否重跑审查"
)


def _title_slug(title: str) -> str:
    """模型按标题反推 ref 时的 slug 形态（sanitize_slug 截断前的全量形态）。"""
    return re.sub(r"([^\w]|_)+", "-", title).strip("-").lower()


def _date_of(stem: str) -> str:
    return stem.split("-")[1]


def _make_store(tmp_path: Path, title: str = LONG_TITLE) -> tuple[ExperienceStore, str]:
    store = ExperienceStore(tmp_path / "experiences")
    doc = ExperienceDocument(
        title=title,
        scenario="并发写者已 push 目标提交时，审查资格被判失效",
        root_cause="先跑审查后看远端，顺序反了",
        solution="先查远端是否已含目标提交，再决定是否重跑审查",
        evidence="tests/unit/test_experience_ref_resolution.py",
        tags=["git_push", "review"],
        source={"session": "s-regression"},
        record_kind="experience",
        verification_state="verified",
    )
    filename = store.save(doc)
    return store, filename.removesuffix(".md")


def _title_derived_ref(stem: str, title: str = LONG_TITLE) -> str:
    return f"EXPERIENCE-{_date_of(stem)}-{_title_slug(title)}"


def test_incident_shape_is_reproduced(tmp_path: Path) -> None:
    """事故形态确实存在：title 全 slug 超过 50 字符截断线，磁盘上没有该文件名。"""
    store, stem = _make_store(tmp_path)
    full_slug = _title_slug(LONG_TITLE)
    assert len(full_slug) > 50, "回归前提：标题 slug 必须超过 sanitize_slug 截断线"
    assert stem.endswith(full_slug[:50])
    assert store.get(_title_derived_ref(stem)) is None


def test_resolve_id_maps_title_derived_ref_to_canonical_stem(tmp_path: Path) -> None:
    store, stem = _make_store(tmp_path)
    resolved = store.resolve_id(_title_derived_ref(stem))
    assert resolved is not None
    canonical, doc = resolved
    assert canonical == stem
    assert doc.title == LONG_TITLE


def test_resolve_id_keeps_exact_stem_semantics(tmp_path: Path) -> None:
    """精确文件名形态零回归：resolve 与 get 指向同一张卡。"""
    store, stem = _make_store(tmp_path)
    resolved = store.resolve_id(stem)
    assert resolved is not None
    assert resolved[0] == stem
    assert resolved[1].title == LONG_TITLE
    assert store.resolve_id(stem + ".md") is not None


def test_record_use_accepts_title_derived_ref(tmp_path: Path) -> None:
    """record_use：按 title 反推的 ref 也要能落账，且落 canonical ref。"""
    store, stem = _make_store(tmp_path)
    entry = store.record_use(
        _title_derived_ref(stem),
        use_decision="applied",
        note="EVO-20261031-a72df001 回归",
        evidence_refs=["episode:ref-resolution"],  # EVO-20261104-e5f79db8 采纳证据强制
    )
    assert entry["experience_ref"] == f"experience:{stem}"


def test_update_status_accepts_title_derived_ref(tmp_path: Path) -> None:
    """状态流转（archive/invalidate/restore）同样接受等价形态。"""
    store, stem = _make_store(tmp_path)
    assert store.update_status(_title_derived_ref(stem), "archived") is True
    reloaded = store.get(stem)
    assert reloaded is not None
    assert reloaded.status == "archived"


def test_search_exact_hydration_accepts_title_derived_ref(tmp_path: Path) -> None:
    """search 精确水合与 record_use 同源：等价形态命中同一张卡且回 canonical ref。"""
    store, stem = _make_store(tmp_path)
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=store)
    rows = searcher._search_experience(_title_derived_ref(stem), 5)
    assert rows, "等价形态必须在精确水合路径命中"
    assert rows[0].get("experience_ref") == f"experience:{stem}"


def test_ambiguous_ref_fails_closed(tmp_path: Path) -> None:
    """多张卡同档命中 → 不静默任选一张（fail-closed）。"""
    store, first = _make_store(tmp_path, "同一个标题前缀用于制造歧义的卡片内容示例")
    store_two = ExperienceStore(tmp_path / "experiences")
    second_doc = ExperienceDocument(
        title="同一个标题前缀用于制造歧义的卡片内容示例二",
        scenario="s",
        root_cause="r",
        solution="sol",
        evidence="e",
        tags=["t"],
        source={},
    )
    second_file = store_two.save(second_doc)
    second = second_file.removesuffix(".md")
    assert first != second
    # 候选是两张卡标题的公共前缀 → 同档命中两张 → 必须返回 None（不猜）
    candidate = f"EXPERIENCE-{_date_of(first)}-同一个标题前缀用于制造歧义"
    assert store.resolve_id(candidate) is None, "歧义形态必须返回 None 而不是猜一张"


def test_free_text_query_is_not_resolved_to_a_card(tmp_path: Path) -> None:
    """防退化：自由文本查询不得被宽松解析压成单卡命中（广搜语义不变）。"""
    store, _ = _make_store(tmp_path)
    assert store.resolve_id("git_push 审查资格在并发写者下于 PASS 之后失效") is None
    assert store.resolve_id("第三方 skill 安装的安全检查清单") is None
    assert store.resolve_id("") is None


def test_near_miss_candidates_report_dir_and_cards(tmp_path: Path) -> None:
    """未找到时的诊断素材：经验库目录 + 近邻候选卡。"""
    store, stem = _make_store(tmp_path)
    candidates = store.near_miss_candidates(_title_derived_ref(stem))
    assert any(item["ref"] == f"experience:{stem}" for item in candidates)
    assert str(store.experiences_dir)
