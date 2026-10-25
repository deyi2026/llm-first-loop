"""P0 held-out 防线单元测试（guard 本体：check_text / find_manifest / 缓存 / 兼容 API）.

后续（步骤 c）将在本文件追加：三个 store 写侧 fail-closed、search 读侧过滤、
evals/heldout/v1/filter.py 薄 CLI 的测试。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import ExperienceStore
from llm_loop.introspection.search import RecordSearcher
from llm_loop.knowledge import heldout_guard
from llm_loop.knowledge.heldout_guard import (
    HeldoutContaminationError,
    assert_not_heldout,
    check_text,
    find_manifest,
)
from llm_loop.memory.store import MemoryEntry, MemoryStore
from llm_loop.methods.store import MethodStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_MANIFEST = _REPO_ROOT / "evals" / "heldout" / "v1" / "manifest.json"

_TASK_ID = "holdout_99_abcdef01"
# 与真实题面风格相近但**自造**的正文（不取真实 held-out 文本进测试代码）
_BODY = (
    "仓库中存在一个特殊的配置文件，需要你核实其中的端口号是否与文档一致，"
    "并说明核实的工具与依据，最后给出结论与建议，同时列出所有被否定的假设。"
)


def _make_heldout_tree(tmp_path: Path, *, task_id: str = _TASK_ID) -> Path:
    root = tmp_path / "evals" / "heldout" / "v1"
    task_dir = root / "tasks" / task_id
    task_dir.mkdir(parents=True)
    (task_dir / "statement.md").write_text(
        f"# 标题行应当被忽略\n\n{_BODY}\n", encoding="utf-8"
    )
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps({"version": "t", "tasks": [{"task_id": task_id}]}), encoding="utf-8"
    )
    return manifest


@pytest.fixture(autouse=True)
def _clean_state():
    heldout_guard.reset_cache()
    yield
    heldout_guard.reset_cache()


# ── check_text 基本判定 ──────────────────────────────────────────────


def test_empty_and_none_text_are_clean(tmp_path):
    mp = _make_heldout_tree(tmp_path)
    assert check_text("", manifest_path=mp)["status"] == "clean"
    assert check_text(None, manifest_path=mp)["status"] == "clean"


def test_task_id_probe_blocks(tmp_path):
    mp = _make_heldout_tree(tmp_path)
    r = check_text(f"复盘结论参见 {_TASK_ID} 的执行轨迹。", manifest_path=mp)
    assert r == {
        "status": "blocked",
        "reason": "task_id",
        "task_id": _TASK_ID,
    }


def test_statement_mid_fragment_blocks(tmp_path):
    """题面正文中段片段（≥48 字窗口）必须被抓（statement_probe）。"""
    mp = _make_heldout_tree(tmp_path)
    norm = " ".join(_BODY.split())
    mid = len(norm) // 2
    frag = norm[mid : mid + 60]
    r = check_text(f"方法卡描述：{frag}，据此沉淀经验。", manifest_path=mp)
    assert r["status"] == "blocked"
    assert r["reason"] == "statement_probe"
    assert r["task_id"] == _TASK_ID


def test_statement_tail_fragment_blocks(tmp_path):
    mp = _make_heldout_tree(tmp_path)
    norm = " ".join(_BODY.split())
    r = check_text("经验正文提到：" + norm[-60:], manifest_path=mp)
    assert r["status"] == "blocked"
    assert r["reason"] == "statement_probe"


def test_statement_32char_fragment_at_unaligned_offset_blocks(tmp_path):
    """32 字连续引用、起点不落在 4 的倍数上（窗口起点区间 [s, s+8] 仍必含
    网格点）也必须被抓——24 字/步长 4 网格的几何保证（48 字 3 窗口方案
    对 <48 字引用 recall=0 的缺陷回归）。"""
    mp = _make_heldout_tree(tmp_path)
    norm = " ".join(_BODY.split())
    assert len(norm) >= 40
    for start in (1, 5, 7, 11):  # 覆盖 mod 4 的各余数（0 之外的代表性偏移）
        frag = norm[start : start + 32]
        assert len(frag) == 32
        r = check_text(f"方法卡描述：{frag}，据此沉淀。", manifest_path=mp)
        assert r["status"] == "blocked", f"offset={start} 未命中"
        assert r["reason"] == "statement_probe"


def test_normal_chinese_technical_paragraph_is_clean_against_window_probes(tmp_path):
    """负例：与题面无关的普通中文技术句在 24 字窗口探针下必须放行。"""
    mp = _make_heldout_tree(tmp_path)
    r = check_text(
        "重构检索层时先把扫描与排序拆开，再为排序补充稳定性测试；"
        "上线前核对缓存键与过期策略，避免新旧键并存。",
        manifest_path=mp,
    )
    assert r["status"] == "clean"
    assert r["task_id"] == ""


def test_statement_probe_survives_whitespace_normalization(tmp_path):
    """待检文本空白形态不同（换行/制表/多空格）也必须命中。"""
    mp = _make_heldout_tree(tmp_path)
    norm = " ".join(_BODY.split())
    scattered = norm[:60].replace(" ", "\n\t ")
    r = check_text(f"开头\n{scattered}\n结尾", manifest_path=mp)
    assert r["status"] == "blocked"


def test_normal_chinese_technical_sentence_is_clean(tmp_path):
    mp = _make_heldout_tree(tmp_path)
    r = check_text("今天我要修复一个解析器的空指针缺陷，先写回归测试再改实现。", manifest_path=mp)
    assert r["status"] == "clean"
    assert r["task_id"] == ""


def test_short_statement_whole_body_is_probe(tmp_path):
    """正文短于 48 字 → 整段即探针。"""
    root = tmp_path / "evals" / "heldout" / "v1"
    tid = "holdout_98_short"
    (root / "tasks" / tid).mkdir(parents=True)
    short_body = "请核实端口并给结论，说明依据。"
    (root / "tasks" / tid / "statement.md").write_text(
        f"# 标题\n\n{short_body}\n", encoding="utf-8"
    )
    mp = root / "manifest.json"
    mp.write_text(json.dumps({"tasks": [{"task_id": tid}]}), encoding="utf-8")
    assert check_text(f"引用：{short_body}。", manifest_path=mp)["status"] == "blocked"


def test_text_cap_200k(tmp_path):
    """截断到前 200_000 字符：前段命中仍 blocked，200k 之后的文本不参与匹配。"""
    mp = _make_heldout_tree(tmp_path)
    norm = " ".join(_BODY.split())
    mid = len(norm) // 2
    frag = norm[mid : mid + 60]
    huge_prefix = "水" * 199_000
    assert check_text(huge_prefix + frag, manifest_path=mp)["status"] == "blocked"
    far = "x" * 200_001
    assert check_text(far + frag, manifest_path=mp)["status"] == "clean"


# ── unavailable（fail-open）路径 ────────────────────────────────────


def test_missing_manifest_path_is_unavailable(tmp_path):
    r = check_text("任意文本", manifest_path=tmp_path / "no_such_manifest.json")
    assert r["status"] == "unavailable"
    assert r["reason"].startswith("manifest_unreadable")


def test_bad_json_manifest_is_unavailable(tmp_path):
    mp = tmp_path / "manifest.json"
    mp.write_text("{ not json", encoding="utf-8")
    r = check_text("任意文本", manifest_path=mp)
    assert r["status"] == "unavailable"
    assert "JSONDecodeError" in r["reason"]


def test_invalid_manifest_shape_is_unavailable(tmp_path):
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps({"tasks": "not-a-list"}), encoding="utf-8")
    r = check_text("任意文本", manifest_path=mp)
    assert r["status"] == "unavailable"
    assert "ValueError" in r["reason"]


def test_missing_statement_file_degrades_to_task_id_only(tmp_path):
    """statement.md 不可读 → 该 task 仅剩 task_id 探针（fail-open 不误报）。"""
    mp = _make_heldout_tree(tmp_path)
    (mp.parent / "tasks" / _TASK_ID / "statement.md").unlink()
    norm = " ".join(_BODY.split())
    r = check_text(norm[:60], manifest_path=mp)
    assert r["status"] == "clean"
    assert check_text(f"见 {_TASK_ID}", manifest_path=mp)["status"] == "blocked"


# ── find_manifest 发现优先级 ─────────────────────────────────────────


def test_find_manifest_env_priority(tmp_path, monkeypatch):
    mp = _make_heldout_tree(tmp_path)
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    monkeypatch.chdir(tmp_path / "elsewhere" if (tmp_path / "elsewhere").mkdir() else tmp_path)
    assert find_manifest() == mp


def test_find_manifest_env_missing_falls_through_to_cwd(tmp_path, monkeypatch):
    mp = _make_heldout_tree(tmp_path)
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(tmp_path / "ghost.json"))
    monkeypatch.chdir(tmp_path)
    assert find_manifest() == mp


def test_find_manifest_cwd_upward_search(tmp_path, monkeypatch):
    mp = _make_heldout_tree(tmp_path)
    monkeypatch.delenv("LFL_HELDOUT_MANIFEST", raising=False)
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    assert find_manifest() == mp


def test_find_manifest_package_root_fallback(tmp_path, monkeypatch):
    """cwd 链上无 evals/heldout 时回落到包路径推导的仓库根。"""
    monkeypatch.delenv("LFL_HELDOUT_MANIFEST", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert find_manifest() == _REAL_MANIFEST


# ── 缓存行为 ────────────────────────────────────────────────────────


def test_manifest_cache_invalidated_by_content_change(tmp_path):
    mp = _make_heldout_tree(tmp_path)
    assert check_text("干净文本", manifest_path=mp)["status"] == "clean"
    # 重写 manifest：换 task_id 且内容长度不同（size 变化 → 缓存 key 变化）
    other = "holdout_77_zzzz"
    mp.write_text(
        json.dumps({"tasks": [{"task_id": other}]}) + " " * 8, encoding="utf-8"
    )
    assert check_text(f"引用 {other}", manifest_path=mp)["status"] == "blocked"
    # 旧 task_id 已不在新 manifest 中
    assert check_text(f"引用 {_TASK_ID}", manifest_path=mp)["status"] == "clean"


def test_use_cache_false_bypasses_cache(tmp_path):
    mp = _make_heldout_tree(tmp_path)
    assert check_text("x", manifest_path=mp, use_cache=False)["status"] == "clean"
    assert heldout_guard._MANIFEST_CACHE == {}
    assert heldout_guard._PROBE_CACHE == {}


def test_reset_cache_clears_entries(tmp_path):
    mp = _make_heldout_tree(tmp_path)
    check_text("预热缓存", manifest_path=mp)
    assert heldout_guard._PROBE_CACHE
    heldout_guard.reset_cache()
    assert heldout_guard._MANIFEST_CACHE == {}
    assert heldout_guard._PROBE_CACHE == {}


# ── 旧签名兼容 API ──────────────────────────────────────────────────


def test_assert_not_heldout_pass_and_block(tmp_path, monkeypatch):
    mp = _make_heldout_tree(tmp_path)
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    assert assert_not_heldout("今天修复一个解析器缺陷。") is None
    assert assert_not_heldout("") is None
    reason = assert_not_heldout(f"见 {_TASK_ID}")
    assert isinstance(reason, str)
    assert _TASK_ID in reason
    assert "泄漏" in reason


def test_assert_not_heldout_accepts_manifest_dict(tmp_path, monkeypatch):
    mp = _make_heldout_tree(tmp_path)
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    man = json.loads(mp.read_text(encoding="utf-8"))
    assert assert_not_heldout("普通句子", man) is None
    reason = assert_not_heldout(f"引用 {_TASK_ID}", man)
    assert reason is not None and _TASK_ID in reason


def test_assert_not_heldout_accepts_manifest_path(tmp_path):
    mp = _make_heldout_tree(tmp_path)
    assert assert_not_heldout("普通句子", str(mp)) is None
    assert assert_not_heldout(f"引用 {_TASK_ID}", str(mp)) is not None


def test_heldout_contamination_error_is_importable():
    assert issubclass(HeldoutContaminationError, Exception)


# ── 真实仓库 manifest 冒烟（不修改任何真实数据） ────────────────────


def test_real_repo_manifest_clean_text_is_clean():
    assert check_text("今天我要修复一个解析器的空指针缺陷，先写回归测试再改实现。")[
        "status"
    ] == "clean"


def test_real_repo_manifest_task_id_blocks():
    r = check_text("复盘引用了 holdout_00_91d3614a 的样本结论。", use_cache=False)
    assert r == {
        "status": "blocked",
        "reason": "task_id",
        "task_id": "holdout_00_91d3614a",
    }


# ── (c1) 写侧 fail-closed：三个 store ────────────────────────────────

_BLOCKED = {"status": "blocked", "reason": "task_id", "task_id": "holdout_x_probe"}
_CLEAN = {"status": "clean", "reason": "no probe hit", "task_id": ""}
_UNAVAILABLE = {"status": "unavailable", "reason": "manifest_not_found", "task_id": ""}


def test_method_store_save_candidate_blocked_rejects_without_write(tmp_path):
    root = tmp_path / "methods"
    store = MethodStore(root, contamination_guard=lambda text: dict(_BLOCKED))
    with pytest.raises(HeldoutContaminationError) as ei:
        store.save_candidate(name="parser-fix", description="普通描述", body="先写回归测试再改实现。")
    # 异常消息只含类别与 task_id，不携带待检文本
    msg = str(ei.value)
    assert "holdout_x_probe" in msg and "task_id" in msg
    assert "普通描述" not in msg and "回归测试" not in msg
    assert not any(p.suffix == ".md" for p in root.rglob("*"))


def test_method_store_save_candidate_clean_writes(tmp_path):
    store = MethodStore(tmp_path / "methods", contamination_guard=lambda text: dict(_CLEAN))
    record = store.save_candidate(name="parser-fix", description="普通描述", body="先写回归测试再改实现。")
    assert store.get(record.method_ref) is not None


def test_method_store_default_guard_is_lazy_heldout_guard(tmp_path, monkeypatch):
    """构造不注入 guard：save 时惰性走 heldout_guard.check_text（env manifest 生效）。"""
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "methods"
    store = MethodStore(root)  # 默认惰性守卫
    with pytest.raises(HeldoutContaminationError) as ei:
        store.save_candidate(name="parser-fix", description=f"复盘参见 {_TASK_ID}", body="正文一行。")
    assert _TASK_ID in str(ei.value)
    assert not any(p.suffix == ".md" for p in root.rglob("*"))


def test_experience_store_save_blocked_rejects_without_write(tmp_path):
    root = tmp_path / "experiences"
    doc = ExperienceDocument(
        title="解析器空指针修复",
        scenario="回归场景",
        root_cause="空指针",
        solution="先写测试",
        evidence="回归绿",
        tags=["parser"],
        source={"kind": "fixture"},
    )
    store = ExperienceStore(root, contamination_guard=lambda text: dict(_BLOCKED))
    with pytest.raises(HeldoutContaminationError) as ei:
        store.save(doc)
    assert "holdout_x_probe" in str(ei.value)
    assert "解析器空指针修复" not in str(ei.value)
    assert not list(root.glob("EXPERIENCE-*.md")) and not root.exists()


def test_experience_store_save_clean_writes(tmp_path):
    root = tmp_path / "experiences"
    doc = ExperienceDocument(
        title="解析器空指针修复",
        scenario="回归场景",
        root_cause="空指针",
        solution="先写测试",
        evidence="回归绿",
        tags=["parser"],
        source={"kind": "fixture"},
    )
    store = ExperienceStore(root, contamination_guard=lambda text: dict(_CLEAN))
    filename = store.save(doc)
    assert (root / filename).is_file()


def test_memory_store_save_entry_blocked_rejects_without_write(tmp_path):
    root = tmp_path / "memory"
    store = MemoryStore(root, contamination_guard=lambda text: dict(_BLOCKED))
    entry = MemoryEntry(id="", type="fact", content="一条普通事实", keywords=["k"])
    with pytest.raises(HeldoutContaminationError) as ei:
        store.save_entry(entry)
    assert "holdout_x_probe" in str(ei.value)
    assert "一条普通事实" not in str(ei.value)
    assert not (root / "index.json").exists()


def test_memory_store_save_entry_if_observed_blocked_rejects_without_write(tmp_path):
    root = tmp_path / "memory"
    store = MemoryStore(root, contamination_guard=lambda text: dict(_BLOCKED))
    entry = MemoryEntry(id="", type="decision", content="一项决定", keywords=[])
    with pytest.raises(HeldoutContaminationError):
        store.save_entry_if_observed(entry, observed_versions={})
    assert not (root / "index.json").exists()


def test_memory_store_save_entry_clean_writes_and_unavailable_fails_open(tmp_path):
    root = tmp_path / "memory"
    unavailable = MemoryStore(root, contamination_guard=lambda text: dict(_UNAVAILABLE))
    saved = unavailable.save_entry(MemoryEntry(id="", type="fact", content="普通事实", keywords=[]))
    assert saved.id and (root / "index.json").exists()
    clean = MemoryStore(root, contamination_guard=lambda text: dict(_CLEAN))
    assert clean.save_entry(MemoryEntry(id="", type="fact", content="普通事实二", keywords=[])).id


# ── P2-7（Rule28 修复轮）：citations / version_history 并入守卫载荷 ──────
# 真实 task_id 来自 evals/heldout/v1/manifest.json tasks[0]（与本文件既有
# 真实仓库 manifest 冒烟同源）；save_entry 与 save_entry_if_observed 共用
# _reject_heldout_contamination，两条路径一并覆盖。


def test_memory_store_citations_with_real_task_id_blocked_no_write(tmp_path):
    """citations 携带真实 holdout task_id → 拒写且零落盘（原口径可绕探针）。"""
    root = tmp_path / "memory"
    store = MemoryStore(root)  # 默认惰性守卫 → 真实仓库 manifest
    entry = MemoryEntry(
        id="",
        type="fact",
        content="一条普通事实正文",
        keywords=[],
        citations=[{"kind": "note", "ref": "evidence://x", "note": "复盘参见 holdout_00_91d3614a"}],
    )
    with pytest.raises(HeldoutContaminationError) as ei:
        store.save_entry(entry)
    assert "holdout_00_91d3614a" in str(ei.value)
    assert "一条普通事实正文" not in str(ei.value)
    assert not (root / "index.json").exists()
    assert not any(p.is_file() for p in root.rglob("*"))


def test_memory_store_version_history_with_real_task_id_blocked_no_write(tmp_path):
    """version_history 携带真实 holdout task_id → 同样拒写且零落盘。"""
    root = tmp_path / "memory"
    store = MemoryStore(root)
    entry = MemoryEntry(
        id="",
        type="decision",
        content="一项普通决定",
        keywords=[],
        version_history=[
            {"version": 1, "content": "旧版内容引用 holdout_00_91d3614a 的结论", "updated_at": "2026-10-25T00:00:00"}
        ],
    )
    with pytest.raises(HeldoutContaminationError) as ei:
        store.save_entry_if_observed(entry, observed_versions={})
    assert "holdout_00_91d3614a" in str(ei.value)
    assert not (root / "index.json").exists()


def test_memory_store_clean_citations_and_version_history_write(tmp_path):
    """正常 citations/version_history（无 id、无题面片段）→ 写入成功（无误伤）。"""
    root = tmp_path / "memory"
    store = MemoryStore(root)
    saved = store.save_entry(
        MemoryEntry(
            id="",
            type="fact",
            content="解析器空指针修复的普通事实",
            keywords=["parser"],
            citations=[{"kind": "source", "ref": "docs/design.md", "note": "设计文档出处"}],
            version_history=[
                {"version": 0, "content": "旧版普通内容", "updated_at": "2026-10-25T00:00:00"}
            ],
        )
    )
    assert saved.id and (root / "index.json").exists()


def test_memory_store_guard_payload_includes_citations_and_version_history(tmp_path):
    """注入守卫可见送检载荷确实含 citations/version_history 文本（送检面可证）。"""
    seen: dict[str, str] = {}

    def guard(text: str) -> dict[str, str]:
        seen["text"] = text
        return dict(_BLOCKED)

    store = MemoryStore(tmp_path / "memory", contamination_guard=guard)
    entry = MemoryEntry(
        id="",
        type="fact",
        content="正文",
        summary="摘要",
        keywords=["k"],
        citations=[{"kind": "note", "ref": "r", "note": "cite-marker-text"}],
        version_history=[{"version": 1, "content": "vh-marker-text", "updated_at": "t"}],
    )
    with pytest.raises(HeldoutContaminationError):
        store.save_entry(entry)
    assert "cite-marker-text" in seen["text"]
    assert "vh-marker-text" in seen["text"]


# ── (c2) 读侧可见过滤：RecordSearcher ────────────────────────────────


def test_search_method_drops_blocked_rows_and_counts(tmp_path, monkeypatch):
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "methods"
    # 种子写入用恒 clean 的注入守卫绕过写侧（读侧测的是检索过滤，不是写入防线）
    seed = MethodStore(root, contamination_guard=lambda text: dict(_CLEAN))
    seed.save_candidate(
        name="parser-fix", description="解析器 回归 修复经验", body="先写回归测试再改实现。"
    )
    seed.save_candidate(
        name="tainted", description=f"解析器 回归 复盘 {_TASK_ID}", body="另一段正文。"
    )
    # 检索侧默认守卫（惰性 heldout_guard.check_text）→ env manifest 生效
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", method_store=MethodStore(root))
    rows = searcher.search(kind="method", query="解析器 回归", limit=10)
    summaries = [str(r.get("summary") or "") for r in rows]
    assert summaries and all(_TASK_ID not in s for s in summaries)
    assert any("修复经验" in s for s in summaries)
    assert searcher._last_heldout_filter == {"dropped": 1, "task_ids": [_TASK_ID]}
    # 无丢弃的检索：入口重置后保持 None（不残留上一次的计数）
    searcher.search(kind="method", query="不存在的关键词xyzq", limit=10)
    assert searcher._last_heldout_filter is None


def test_search_experience_drops_blocked_rows_and_counts(tmp_path, monkeypatch):
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "experiences"
    seed = ExperienceStore(root, contamination_guard=lambda text: dict(_CLEAN))
    seed.save(
        ExperienceDocument(
            title="普通检索经验",
            scenario="s",
            root_cause="r",
            solution="so",
            evidence="e",
            tags=["t"],
            source={"kind": "fixture"},
        )
    )
    seed.save(
        ExperienceDocument(
            title=f"复盘 {_TASK_ID}",
            scenario="s2",
            root_cause="r",
            solution="so",
            evidence="e",
            tags=["t"],
            source={"kind": "fixture"},
        )
    )
    searcher = RecordSearcher(
        audit_dir=tmp_path / "audit", experience_store=ExperienceStore(root)
    )
    rows = searcher.search(kind="experience", query="", limit=10)
    summaries = [str(r.get("summary") or "") for r in rows]
    assert summaries == ["普通检索经验"]
    assert searcher._last_heldout_filter == {"dropped": 1, "task_ids": [_TASK_ID]}


# ── (c3) filter.py 薄 CLI ────────────────────────────────────────────

_FILTER = _REPO_ROOT / "evals" / "heldout" / "v1" / "filter.py"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "LFL_HELDOUT_MANIFEST"}
    return subprocess.run(
        [sys.executable, str(_FILTER), *args],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env=env,
    )


def test_filter_cli_selfcheck_exit_zero():
    proc = _run_cli("--selfcheck")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 failure" in proc.stdout


def test_filter_cli_text_task_id_hit_exit_two():
    proc = _run_cli("--text", "复盘引用了 holdout_00_91d3614a 的样本结论。")
    assert proc.returncode == 2
    assert "BLOCKED" in proc.stdout
    assert "holdout_00_91d3614a" in proc.stdout


def test_filter_cli_text_clean_exit_zero():
    proc = _run_cli("--text", "今天我要修复一个解析器的空指针缺陷，先写回归测试再改实现。")
    assert proc.returncode == 0
    assert "OK" in proc.stdout


# ── (d1) P1 回归：save_candidate 整卡封堵（aliases 等全部落盘字段） ───


def test_method_store_save_candidate_alias_with_task_id_blocks_without_write(tmp_path, monkeypatch):
    """aliases 含真实 task_id 必须拒写（落盘序列化文本封堵），且磁盘零落盘."""
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "methods"
    store = MethodStore(root)  # 默认惰性守卫 → env manifest 生效
    with pytest.raises(HeldoutContaminationError) as ei:
        store.save_candidate(
            name="parser-fix",
            description="普通描述",
            body="先写回归测试再改实现。",
            # 该 alias 可通过门控（长度/字符/泛化/重复/df）后仍含真实 task_id：
            # 模拟 learning_plane 直通的模型 payload 别名污染
            aliases=[f"复盘入口-{_TASK_ID}"],
        )
    msg = str(ei.value)
    # 异常消息只含类别与 task_id，不携带待检文本（name/description/body/alias 原文）
    assert _TASK_ID in msg and "task_id" in msg
    assert "普通描述" not in msg and "回归测试" not in msg and "复盘入口" not in msg
    # 磁盘零落盘：目标目录没有任何方法卡
    assert not root.exists() or not any(p.suffix == ".md" for p in root.rglob("*"))


def test_method_store_save_candidate_normal_chinese_aliases_write(tmp_path):
    """负例：正常中文 aliases 不误报，照常落盘并在记录上可见."""
    root = tmp_path / "methods"
    store = MethodStore(root, contamination_guard=lambda text: dict(_CLEAN))
    record = store.save_candidate(
        name="parser-fix",
        description="普通描述",
        body="先写回归测试再改实现。",
        aliases=["解析器修复", "空指针回归"],
    )
    assert set(record.aliases) == {"解析器修复", "空指针回归"}
    assert store.get(record.method_ref) is not None


# ── (d2) P2 回归：读侧 scenario / dict(source) 展平检查 ──────────────


def _seed_experience(root: Path, *, title: str, scenario: str, source: dict | None = None) -> str:
    """用恒 clean 的注入守卫种入经验行（读侧测过滤，不测写入防线）."""
    seed = ExperienceStore(root, contamination_guard=lambda text: dict(_CLEAN))
    return seed.save(
        ExperienceDocument(
            title=title,
            scenario=scenario,
            root_cause="原因",
            solution="做法",
            evidence="证据",
            tags=["t"],
            source=source if source is not None else {"kind": "fixture"},
        )
    )


def test_search_experience_scenario_task_id_dropped_in_discovery_and_hydrate(
    tmp_path, monkeypatch, caplog
):
    """scenario 含 task_id：discovery 与 exact-hydrate 两条路径都丢弃并计数."""
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "experiences"
    clean_file = _seed_experience(root, title="普通检索经验", scenario="回归场景下复现")
    tainted_file = _seed_experience(root, title="题面复盘经验", scenario=f"复盘参见 {_TASK_ID}")
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=ExperienceStore(root))
    with caplog.at_level(logging.INFO, logger="llm_loop.introspection.search"):
        rows = searcher.search(kind="experience", query="", limit=10)
    # discovery：污染行被丢弃，干净行（含正常中文 scenario）保留
    assert [str(r.get("summary") or "") for r in rows] == ["普通检索经验"]
    assert searcher._last_heldout_filter == {"dropped": 1, "task_ids": [_TASK_ID]}
    # 丢弃日志只含 kind/类别/task_id，不含任何行正文
    drops = [r.getMessage() for r in caplog.records if "heldout read filter dropped" in r.getMessage()]
    assert len(drops) == 1
    assert "kind=experience" in drops[0] and "reason=task_id" in drops[0]
    assert _TASK_ID in drops[0]
    assert "题面复盘经验" not in drops[0] and "复盘参见" not in drops[0]
    # exact-hydrate：污染行同样被丢弃并计数
    tainted_stem = tainted_file.removesuffix(".md")
    assert searcher.search(kind="experience", query=f"experience:{tainted_stem}", limit=10) == []
    assert searcher._last_heldout_filter == {"dropped": 1, "task_ids": [_TASK_ID]}
    # 负例：干净行的精确水合照常返回且不计数
    clean_stem = clean_file.removesuffix(".md")
    ok = searcher.search(kind="experience", query=f"experience:{clean_stem}", limit=10)
    assert len(ok) == 1 and ok[0].get("summary") == "普通检索经验"
    assert searcher._last_heldout_filter is None


def test_search_experience_source_dict_value_flattened_and_checked(tmp_path, monkeypatch):
    """dict 值（source）内嵌 task_id：展平后命中，discovery 与 hydrate 都丢弃."""
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "experiences"
    filename = _seed_experience(
        root,
        title="来源字段带出处的经验",
        scenario="普通场景",
        source={"kind": "fixture", "note": f"出处 {_TASK_ID}"},
    )
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=ExperienceStore(root))
    assert searcher.search(kind="experience", query="", limit=10) == []
    assert searcher._last_heldout_filter == {"dropped": 1, "task_ids": [_TASK_ID]}
    stem = filename.removesuffix(".md")
    assert searcher.search(kind="experience", query=f"experience:{stem}", limit=10) == []
    assert searcher._last_heldout_filter == {"dropped": 1, "task_ids": [_TASK_ID]}


# ── (e1) P1-A：annotate_freshness / annotate_aliases 写侧封堵 ────────


def _seed_method_card(root: Path) -> str:
    """用恒 clean 的注入守卫种入一张方法卡（写侧测封堵，不测既有防线）."""
    store = MethodStore(root, contamination_guard=lambda text: dict(_CLEAN))
    record = store.save_candidate(
        name="parser-fix", description="解析器 回归 修复经验", body="先写回归测试再改实现。"
    )
    return record.method_ref


def test_annotate_freshness_task_id_rejected_card_unchanged(tmp_path, monkeypatch):
    """P1-A：freshness_refs 带 task_id（相对路径形态，绕过 .. / 绝对路径检查）
    必须在落盘前被拒——METHOD.md 逐字节不变、annotations.jsonl 零写入。"""
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "methods"
    method_ref = _seed_method_card(root)
    card_path = root / method_ref.removeprefix("method:") / "METHOD.md"
    before = card_path.read_bytes()
    store = MethodStore(root)  # 默认惰性守卫 → env manifest 生效
    with pytest.raises(HeldoutContaminationError) as ei:
        store.annotate_freshness(method_ref, [f"reports/{_TASK_ID}-note.md"])
    assert _TASK_ID in str(ei.value)
    assert card_path.read_bytes() == before
    assert not (root / "annotations.jsonl").exists()
    # 负例：干净的 workspace 相对路径照常落卡（frontmatter 只改这一个键）
    store.annotate_freshness(method_ref, ["reports/deploy.md"])
    assert "reports/deploy.md" in (card_path.read_text(encoding="utf-8"))


def test_annotate_aliases_task_id_rejected_card_unchanged(tmp_path, monkeypatch):
    """同构写路径（当前无调用方，防止将来接线即漏）：aliases 带 task_id 拒写。"""
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "methods"
    method_ref = _seed_method_card(root)
    card_path = root / method_ref.removeprefix("method:") / "METHOD.md"
    before = card_path.read_bytes()
    store = MethodStore(root)
    with pytest.raises(HeldoutContaminationError) as ei:
        store.annotate_aliases(method_ref, [f"复盘入口-{_TASK_ID}"])
    assert _TASK_ID in str(ei.value)
    assert card_path.read_bytes() == before
    assert not (root / "annotations.jsonl").exists()
    # 负例：正常中文 alias 照常写入（门控通过 + 守卫不误报）
    rec, dropped = store.annotate_aliases(method_ref, ["解析器修复"])
    assert "解析器修复" in rec.aliases


def test_update_status_clean_card_still_transitions(tmp_path, monkeypatch):
    """封堵点②的负例：干净卡的生命周期流转不受守卫影响。"""
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "methods"
    method_ref = _seed_method_card(root)
    store = MethodStore(root)
    updated = store.update_status(method_ref, "active")
    assert updated.status == "active"


# ── (e2) P1-B：两侧 record_use note 入账封堵 ─────────────────────────


def test_method_record_use_note_task_id_rejected_no_ledger(tmp_path, monkeypatch):
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "methods"
    method_ref = _seed_method_card(root)
    store = MethodStore(root)
    with pytest.raises(HeldoutContaminationError) as ei:
        store.record_use(
            method_ref,
            episode_ref="episode:test-1",
            decision="applied",
            note=f"本任务({_TASK_ID})按卡执行成功",
        )
    assert _TASK_ID in str(ei.value)
    assert "本任务" not in str(ei.value)
    assert not (root / "usage.jsonl").exists()
    # 负例：干净 note 正常入账且账本可读回
    entry = store.record_use(
        method_ref, episode_ref="episode:test-1", decision="applied", note="按卡执行成功"
    )
    assert entry["note"] == "按卡执行成功"
    assert store.usage_entries(method_ref)[0]["note"] == "按卡执行成功"


def test_experience_record_use_note_task_id_rejected_no_ledger(tmp_path, monkeypatch):
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "experiences"
    filename = _seed_experience(root, title="普通检索经验", scenario="回归场景下复现")
    store = ExperienceStore(root)
    with pytest.raises(HeldoutContaminationError) as ei:
        store.record_use(
            filename,
            use_decision="applied",
            note=f"本任务({_TASK_ID})套用了该经验",
            episode_ref="episode:test-1",
        )
    assert _TASK_ID in str(ei.value)
    assert not (root / "usage.jsonl").exists()
    # 负例：干净 note 正常入账
    entry = store.record_use(filename, use_decision="applied", note="套用成功")
    assert entry["note"] == "套用成功"


def test_method_record_qualification_note_task_id_rejected(tmp_path, monkeypatch):
    """grep 补充项：record_qualification 的 note/evidence_refs 同类模型文本
    （qualification.jsonl 追加路径）同样整行封堵。"""
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "methods"
    method_ref = _seed_method_card(root)
    store = MethodStore(root)
    qpath = root / method_ref.removeprefix("method:") / "qualification.jsonl"
    with pytest.raises(HeldoutContaminationError) as ei:
        store.record_qualification(
            method_ref,
            task_ref="episode:test-1",
            verdict="fail",
            note=f"复盘参见 {_TASK_ID}",
        )
    assert _TASK_ID in str(ei.value)
    assert not qpath.exists()
    # 负例：干净 note 正常入账
    entry = store.record_qualification(
        method_ref, task_ref="episode:test-1", verdict="fail", note="步骤二前提不成立"
    )
    assert entry["note"] == "步骤二前提不成立"
    assert qpath.is_file()


# ── (e3) F3：ExperienceStore.save 最终 payload（supersedes 追加后）复检 ─


def test_experience_save_supersedes_injected_task_id_rejected(tmp_path, monkeypatch):
    """near-dup 链接发生在入口预检之后：追加的 stem 若带入 task_id，
    锁内写盘前的最终 payload 复检必须拒写，零落盘。"""
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "experiences"
    store = ExperienceStore(root)
    monkeypatch.setattr(
        store, "_find_near_duplicate_ids", lambda filename, doc: [f"EXPERIENCE-20260101-{_TASK_ID}"]
    )
    with pytest.raises(HeldoutContaminationError) as ei:
        store.save(
            ExperienceDocument(
                title="普通经验",
                scenario="s",
                root_cause="r",
                solution="so",
                evidence="e",
                tags=["t"],
                source={"kind": "fixture"},
            )
        )
    assert _TASK_ID in str(ei.value)
    assert not list(root.glob("EXPERIENCE-*.md"))


def test_experience_update_status_final_payload_rechecked(tmp_path, monkeypatch):
    """status RMW 同构封堵：存量污染卡（DI 守卫绕过写入模拟）不得借状态
    流转重新落盘。"""
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "experiences"
    filename = _seed_experience(root, title=f"复盘 {_TASK_ID}", scenario="普通场景")
    store = ExperienceStore(root)  # 默认守卫
    with pytest.raises(HeldoutContaminationError):
        store.update_status(filename, "archived")
    # 负例：干净卡状态流转照常
    clean_file = _seed_experience(root, title="干净经验", scenario="普通场景二")
    assert ExperienceStore(root).update_status(clean_file, "archived") is True


# ── (e4) F5：memory_extract 审计写入接线 ─────────────────────────────


def test_memory_extract_audit_contaminated_failures_skipped(tmp_path, monkeypatch):
    from llm_loop.memory.extractor import MemoryExtractor

    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    audit_dir = tmp_path / "audit"
    extractor = MemoryExtractor(None, None, None, audit_dir=audit_dir)
    # failures 内嵌模型输出解析失败摘录，含 task_id → 整行拒写
    extractor._audit("sess-1", "manual", "会话全量", 10, [f"解析失败: 引用 {_TASK_ID}"])
    assert not (audit_dir / "memory_extract_log.jsonl").exists()
    # 负例：干净 failures/note 照常落盘且可读回
    extractor._audit("sess-1", "manual", "会话全量", 10, ["格式不符"], note="部分跳过")
    log = (audit_dir / "memory_extract_log.jsonl").read_text(encoding="utf-8")
    assert log.count("\n") == 1 and "格式不符" in log


# ── (e5) P1-B 读侧回流：recent_issue / freshness_refs 整行过滤 ──────


def _tainted_method_use_row(tmp_path: Path, method_ref: str) -> None:
    """用恒 clean 的注入守卫把带 task_id 的 note 落进 usage 账本
    （模拟守卫上线前的存量数据/旁路写入；读侧测过滤，不测写入防线）。"""
    store = MethodStore(tmp_path / "methods", contamination_guard=lambda text: dict(_CLEAN))
    store.record_use(
        method_ref,
        episode_ref="episode:test-1",
        decision="rejected",
        benefit="hindered",
        note=f"本任务({_TASK_ID})卡的前提不成立",
    )


def test_search_method_recent_issue_reflux_dropped_and_counted(tmp_path, monkeypatch):
    """P1-B 读侧：usage_feedback 把账本 note 合进行（recent_issue）——
    过滤必须在 _annotate_usage 之后，污染行丢弃并计数（discovery 与
    exact-hydrate 两条路径）。"""
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "methods"
    method_ref = _seed_method_card(root)
    _tainted_method_use_row(tmp_path, method_ref)
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", method_store=MethodStore(root))
    # exact-hydrate：注解合并 recent_issue 后整行命中 → 丢弃并计数
    assert searcher.search(kind="method", query=method_ref, limit=10) == []
    assert searcher._last_heldout_filter == {"dropped": 1, "task_ids": [_TASK_ID]}
    # discovery：同一条 recent_issue 回流行同样不得外泄
    rows = searcher.search(kind="method", query="解析器 回归", limit=10)
    assert all(_TASK_ID not in json.dumps(r, ensure_ascii=False, default=str) for r in rows)


def _tainted_experience_use_row(tmp_path: Path, filename: str) -> None:
    store = ExperienceStore(tmp_path / "experiences", contamination_guard=lambda text: dict(_CLEAN))
    store.record_use(
        filename,
        use_decision="rejected",
        benefit="hindered",
        note=f"本任务({_TASK_ID})经验前提不成立",
        episode_ref="episode:test-1",
    )


def test_search_experience_recent_issue_reflux_dropped_and_counted(tmp_path, monkeypatch):
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "experiences"
    filename = _seed_experience(root, title="普通检索经验", scenario="回归场景下复现")
    _tainted_experience_use_row(tmp_path, filename)
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", experience_store=ExperienceStore(root))
    stem = filename.removesuffix(".md")
    assert searcher.search(kind="experience", query=f"experience:{stem}", limit=10) == []
    assert searcher._last_heldout_filter == {"dropped": 1, "task_ids": [_TASK_ID]}
    rows = searcher.search(kind="experience", query="", limit=10)
    assert all(_TASK_ID not in json.dumps(r, ensure_ascii=False, default=str) for r in rows)


def test_search_method_freshness_refs_reflux_dropped(tmp_path, monkeypatch):
    """P1-A 读侧：存量卡的 freshness_refs 含 task_id（DI 守卫绕过 annotate
    写入模拟）→ exact-hydrate 整行命中丢弃并计数。"""
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    root = tmp_path / "methods"
    method_ref = _seed_method_card(root)
    MethodStore(root, contamination_guard=lambda text: dict(_CLEAN)).annotate_freshness(
        method_ref, [f"reports/{_TASK_ID}-note.md"]
    )
    searcher = RecordSearcher(audit_dir=tmp_path / "audit", method_store=MethodStore(root))
    assert searcher.search(kind="method", query=method_ref, limit=10) == []
    assert searcher._last_heldout_filter == {"dropped": 1, "task_ids": [_TASK_ID]}
    # 负例：干净卡 + 干净 freshness_refs 的 exact-hydrate 照常返回且不计数
    other = _seed_method_card(root)
    MethodStore(root, contamination_guard=lambda text: dict(_CLEAN)).annotate_freshness(
        other, ["reports/deploy.md"]
    )
    ok = searcher.search(kind="method", query=other, limit=10)
    assert len(ok) == 1 and searcher._last_heldout_filter is None


def test_filter_whole_row_catches_unknown_annotation_field(tmp_path, monkeypatch):
    """结构性负例回归：任何"未来注解字段"（不在任何历史白名单里的新键）
    携带 task_id 的行都会被整行序列化检查丢弃——字段白名单思路的终结。"""
    mp = _make_heldout_tree(tmp_path / "h")
    monkeypatch.setenv("LFL_HELDOUT_MANIFEST", str(mp))
    searcher = RecordSearcher(audit_dir=tmp_path / "audit")
    rows = [
        {"id": "a", "key": "method:a", "summary": "干净行"},
        {"id": "b", "key": "method:b", "summary": "表面干净", "future_note_field": f"参见 {_TASK_ID}"},
    ]
    kept = searcher._filter_heldout_rows(rows, kind="method")
    assert [r["id"] for r in kept] == ["a"]
    assert searcher._last_heldout_filter == {"dropped": 1, "task_ids": [_TASK_ID]}
