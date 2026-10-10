"""ExperienceStore DRC T2 durability 契约测试（#7 迁移，2026-10-08）.

覆盖：
- 写入结果分型：definitely_not_committed（replace/link 前失败）/ commit_outcome_uncertain
  （link/replace 已生效但目录 fsync 未确认）。
- 原子性：update_status 只可能出现整体旧/整体新，崩溃位不产生半卡。
- 跨进程单写者：save 冲突契约（FileExistsError 不覆盖）在并发下仍成立；
  update_status read-modify-write 串行化。
- 读取面 fail-open：损坏旧记录 → update_status 返回 False 且原样保留。
- 孤儿 tmp / lock 文件不可见：不进入 EXPERIENCE-*.md 扫描。
- uncertain exact-readback reconcile：readback matches 即已落盘，重存必然冲突。
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

import pytest

from llm_loop.experiences import store as store_mod
from llm_loop.experiences.document import ExperienceDocument
from llm_loop.experiences.store import (
    ExperienceCommitUncertainError,
    ExperiencePersistError,
    ExperienceStore,
)


def _doc(title: str = "T2 迁移验证") -> ExperienceDocument:
    return ExperienceDocument(
        title=title,
        scenario="durability contract scenario",
        root_cause="bare write_text overwrite",
        solution="tmp O_EXCL -> file fsync -> link/replace -> dir fsync",
        evidence="test_experience_store_durability.py",
        tags=["drc", "t2"],
        source={"test": "test_experience_store_durability"},
        record_kind="experience",
        verification_state="verified",
    )


def _tmp_residue(root: Path) -> list[Path]:
    return sorted(root.glob("*.tmp"))


def test_save_durable_happy_path(tmp_path: Path) -> None:
    store = ExperienceStore(experiences_dir=str(tmp_path))
    doc = _doc()
    filename = store.save(doc)

    path = tmp_path / filename
    assert path.exists()
    restored = ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
    assert restored.title == doc.title
    assert restored.status == "active"
    assert _tmp_residue(tmp_path) == []


def test_save_definitely_not_committed_before_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(_path: Path, _payload: str) -> None:
        raise OSError("simulated disk full")

    monkeypatch.setattr(store_mod, "_write_temp_exclusive", _fail)
    store = ExperienceStore(experiences_dir=str(tmp_path))

    with pytest.raises(ExperiencePersistError):
        store.save(_doc())

    assert list(tmp_path.glob("EXPERIENCE-*.md")) == []
    assert _tmp_residue(tmp_path) == []


def test_save_conflict_contract_never_overwrites(tmp_path: Path) -> None:
    store = ExperienceStore(experiences_dir=str(tmp_path))
    first = _doc(title="冲突契约")
    filename = store.save(first)

    with pytest.raises(FileExistsError):
        store.save(_doc(title="冲突契约"))

    restored = ExperienceDocument.from_md((tmp_path / filename).read_text(encoding="utf-8"))
    assert restored.scenario == first.scenario  # 先写者内容原样保留，未被覆盖


def test_save_commit_uncertain_after_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fsync_fail(_path: Path) -> None:
        raise OSError("simulated dir fsync failure")

    monkeypatch.setattr(store_mod, "_fsync_directory", _fsync_fail)
    store = ExperienceStore(experiences_dir=str(tmp_path))

    with pytest.raises(ExperienceCommitUncertainError) as excinfo:
        store.save(_doc(title="不确定提交"))

    err = excinfo.value
    files = list(tmp_path.glob("EXPERIENCE-*.md"))
    assert len(files) == 1
    on_disk = files[0].read_text(encoding="utf-8")
    # readback：已原子可见且逐字 matches——语义上"已落盘"
    assert err.visible_state == "matches"
    assert err.expected_sha256 == hashlib.sha256(on_disk.encode("utf-8")).hexdigest()
    assert err.experience_id == files[0].name.removesuffix(".md")
    assert ExperienceDocument.from_md(on_disk).title == "不确定提交"
    assert _tmp_residue(tmp_path) == []

    # reconcile 红线：readback 已 matches 后重存同一文档必然冲突（不产生第二份）
    with pytest.raises(FileExistsError):
        store.save(_doc(title="不确定提交"))


def test_update_status_definitely_not_committed_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ExperienceStore(experiences_dir=str(tmp_path))
    filename = store.save(_doc(title="原样保留"))
    path = tmp_path / filename
    before = path.read_text(encoding="utf-8")

    def _fail(_p: Path, _payload: str) -> None:
        raise OSError("simulated tmp write failure")

    monkeypatch.setattr(store_mod, "_write_temp_exclusive", _fail)
    with pytest.raises(ExperiencePersistError):
        store.update_status(filename.removesuffix(".md"), "archived")

    assert path.read_text(encoding="utf-8") == before
    assert _tmp_residue(tmp_path) == []


def test_update_status_uncertain_yields_full_new_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ExperienceStore(experiences_dir=str(tmp_path))
    filename = store.save(_doc(title="整体新或整体旧"))

    calls: list[str] = []

    def _fsync_fail(_path: Path) -> None:
        calls.append("fail")
        raise OSError("simulated dir fsync failure")

    monkeypatch.setattr(store_mod, "_fsync_directory", _fsync_fail)
    experience_id = filename.removesuffix(".md")
    with pytest.raises(ExperienceCommitUncertainError) as excinfo:
        store.update_status(experience_id, "archived")

    assert len(calls) == store_mod._DIR_FSYNC_ATTEMPTS  # 有界重试后分型，不静默吞
    err = excinfo.value
    on_disk = (tmp_path / filename).read_text(encoding="utf-8")
    assert err.visible_state == "matches"
    assert err.experience_id == experience_id
    # 不确定 ≠ 半卡：文件要么整体旧要么整体新，这里必然是整体新且可完整解析
    restored = ExperienceDocument.from_md(on_disk)
    assert restored.status == "archived"
    assert restored.title == "整体新或整体旧"
    assert _tmp_residue(tmp_path) == []


def test_update_status_replace_failure_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ExperienceStore(experiences_dir=str(tmp_path))
    filename = store.save(_doc(title="replace 失败原样"))
    before = (tmp_path / filename).read_text(encoding="utf-8")

    def _replace_fail(_src: Path, _dst: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", _replace_fail)
    with pytest.raises(ExperiencePersistError):
        store.update_status(filename.removesuffix(".md"), "invalidated")

    assert (tmp_path / filename).read_text(encoding="utf-8") == before
    assert _tmp_residue(tmp_path) == []


def test_concurrent_save_single_winner_no_torn_file(tmp_path: Path) -> None:
    store_a = ExperienceStore(experiences_dir=str(tmp_path))
    store_b = ExperienceStore(experiences_dir=str(tmp_path))

    outcomes: list[str] = []
    barrier = threading.Barrier(8)

    def _worker(store: ExperienceStore) -> None:
        barrier.wait()
        try:
            store.save(_doc(title="并发同日同 slug"))
            outcomes.append("saved")
        except FileExistsError:
            outcomes.append("conflict")
        except OSError as exc:
            outcomes.append(f"error:{type(exc).__name__}")

    threads = [threading.Thread(target=_worker, args=(store_a if i % 2 == 0 else store_b,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert outcomes.count("saved") == 1
    assert outcomes.count("conflict") == 7
    files = list(tmp_path.glob("EXPERIENCE-*.md"))
    assert len(files) == 1
    restored = ExperienceDocument.from_md(files[0].read_text(encoding="utf-8"))
    assert restored.title == "并发同日同 slug"
    assert _tmp_residue(tmp_path) == []


def test_concurrent_update_status_serialized_never_torn(tmp_path: Path) -> None:
    store_a = ExperienceStore(experiences_dir=str(tmp_path))
    store_b = ExperienceStore(experiences_dir=str(tmp_path))
    filename = store_a.save(_doc(title="并发状态更新"))
    experience_id = filename.removesuffix(".md")

    results: list[bool] = []
    barrier = threading.Barrier(8)
    statuses = ("archived", "invalidated")

    def _worker(i: int) -> None:
        store = store_a if i % 2 == 0 else store_b
        barrier.wait()
        results.append(store.update_status(experience_id, statuses[i % 2]))

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(results)  # 单写者临界区内 read-modify-write 全部成立
    restored = ExperienceDocument.from_md((tmp_path / filename).read_text(encoding="utf-8"))
    assert restored.status in statuses  # 整体旧/整体新之一，绝不半卡
    assert restored.title == "并发状态更新"
    assert _tmp_residue(tmp_path) == []


def test_corrupted_old_record_fail_open_untouched(tmp_path: Path) -> None:
    garbage = tmp_path / "EXPERIENCE-20260101-corrupt.md"
    garbage.write_text("not-a-valid-front-matter: [", encoding="utf-8")
    store = ExperienceStore(experiences_dir=str(tmp_path))

    assert store.update_status("EXPERIENCE-20260101-corrupt", "archived") is False
    assert garbage.read_text(encoding="utf-8") == "not-a-valid-front-matter: ["


def test_orphan_tmp_and_lock_invisible_to_scans(tmp_path: Path) -> None:
    (tmp_path / "EXPERIENCE-20260101-real.abc123.tmp").write_text("partial", encoding="utf-8")
    store = ExperienceStore(experiences_dir=str(tmp_path))
    filename = store.save(_doc(title="孤儿 tmp 不可见"))

    assert [f.name for f in tmp_path.glob("EXPERIENCE-*.md")] == [filename]
    assert store.get("EXPERIENCE-20260101-real") is None  # 孤儿 tmp 不产生幽灵记录
    assert [r.get("summary") for r in store.list_active()] == ["孤儿 tmp 不可见"]


def test_uncertain_readback_reconcile_is_get_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import contextlib

    fail_calls = {"n": 0}

    def _fsync_fail(_path: Path) -> None:
        fail_calls["n"] += 1
        raise OSError("simulated dir fsync failure")

    monkeypatch.setattr(store_mod, "_fsync_directory", _fsync_fail)
    store = ExperienceStore(experiences_dir=str(tmp_path))

    with pytest.raises(ExperienceCommitUncertainError) as excinfo:
        store.save(_doc(title="readback 兜底"))

    # 调用面 reconcile：uncertain 之后 get(experience_id) 可逐字取回整卡
    restored = store.get(excinfo.value.experience_id)
    assert restored is not None
    assert restored.title == "readback 兜底"
    # fsync 故障消失后（模拟重启恢复），同目录续写不受影响
    monkeypatch.setattr(
        store_mod, "_fsync_directory", contextlib.suppress  # type: ignore[arg-types]
    )
    filename2 = store.save(_doc(title="恢复后续写"))
    assert (tmp_path / filename2).exists()


# ---------------------------------------------------------------------------
# 2026-10-10 回归：sanitize_slug Unicode 塌缩。旧实现只留 ASCII [a-zA-Z0-9]，纯中文/
# 中文开头标题被整体吃掉 → 回退 "untitled" → 同日第二条中文经验同 slug 冲突被拒，
# 不可逆丢失（experiences/ 曾累积 18 个 *-untitled.md）。
# ---------------------------------------------------------------------------


def test_sanitize_slug_preserves_cjk_and_keeps_ascii_legacy() -> None:
    assert ExperienceStore.sanitize_slug("纯中文标题测试") == "纯中文标题测试"
    assert ExperienceStore.sanitize_slug("openJiuwen 竞品分析") == "openjiuwen-竞品分析"
    # 纯 ASCII 行为必须与旧实现逐字节一致：下划线→连字符、连续分隔折叠、小写
    assert ExperienceStore.sanitize_slug("A_B-C!!d") == "a-b-c-d"
    assert ExperienceStore.sanitize_slug("  --Fix: twin  space--  ") == "fix-twin-space"
    # 纯符号仍为空（save() hash 兜底）；50 字符截断保持
    assert ExperienceStore.sanitize_slug("！！！……") == ""
    assert len(ExperienceStore.sanitize_slug("标" * 80)) == 50


def test_save_two_distinct_cjk_titles_same_day_both_persist(tmp_path: Path) -> None:
    store = ExperienceStore(experiences_dir=str(tmp_path))
    first = store.save(_doc(title="第一条中文经验"))
    second = store.save(_doc(title="第二条中文经验"))

    # 修复前：第二条必然 FileExistsError（双双塌缩成 EXPERIENCE-*-untitled.md）
    assert first != second
    assert (tmp_path / first).exists() and (tmp_path / second).exists()
    assert (
        ExperienceDocument.from_md((tmp_path / second).read_text(encoding="utf-8")).title
        == "第二条中文经验"
    )
    assert _tmp_residue(tmp_path) == []


def test_save_symbol_only_titles_get_distinct_hash_fallback(tmp_path: Path) -> None:
    store = ExperienceStore(experiences_dir=str(tmp_path))
    a = store.save(_doc(title="！！！……"))
    b = store.save(_doc(title="？？？——"))

    assert a != b
    assert "untitled-" in a and "untitled-" in b
