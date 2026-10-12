"""学习通道隔离三件套回归（2026-09-23 学习风暴事故）.

事故链：learning 进程引擎从未激活工作区分桶（factory learning 分支提前
return 跳过 set_workspace）→ owner key "." ≠ web 分桶 owner → 读取前台会话
全部 SessionIdConflictError（9.3h 内 240 次 worker_exception）→ 间隔触发器
按 message_count 递增持续生成新任务再失败；每次尝试都是缓存冷的 glm-5.3
大调用（命中率 27-30%），与前台争抢同一远端端点——"反应慢"的机制。

- Fix1：workspace 激活提取为可复用装配步，learning 分支在提前 return 前
  同样激活（与 task 公共路径同一函数，杜绝再次分叉）。
- Fix2：LearningJournal.recent_failure + maybe_trigger 失败退避——会话近期
  有终态失败任务时跳过 interval 入队（机械窗口，非语义判断）。
- Fix3：LearningPlane.model_override（LFL_LEARNING_MODEL）——学习通道模型
  独立配置，缺省回落 source_model（行为不变）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from llm_loop.memory.extractor import MemoryExtractor
from llm_loop.methods.learning_journal import LearningJournal
from llm_loop.methods.learning_plane import LearningPlane

# ---------------------------------------------------------------------------
# Fix 2: journal.recent_failure
# ---------------------------------------------------------------------------


def test_journal_recent_failure_within_window(tmp_path: Path) -> None:
    journal = LearningJournal(tmp_path / "journal.jsonl", candidate_lookup=None)
    job = journal.enqueue(
        "ep-1", session_id="s1", source_model="glm/glm-5.3", kind="memory_extract"
    )
    assert job is not None
    journal.mark_admitted(job.job_id)
    journal.mark_started(job.job_id)
    journal.mark_failed(job.job_id, "worker_exception")

    assert journal.recent_failure("s1", within_s=3600) is True
    assert journal.recent_failure("other-session", within_s=3600) is False
    # 窗口外（伪造历史失败时间）
    assert journal.recent_failure("s1", within_s=0) is False


def test_journal_recent_failure_ignores_success(tmp_path: Path) -> None:
    journal = LearningJournal(tmp_path / "journal.jsonl", candidate_lookup=None)
    job = journal.enqueue("ep-2", session_id="s2", source_model="m", kind="reflection")
    assert job is not None
    journal.mark_admitted(job.job_id)
    journal.mark_started(job.job_id)
    journal.mark_saved(job.job_id, "method:x")
    assert journal.recent_failure("s2", within_s=3600) is False


# ---------------------------------------------------------------------------
# Fix 2: maybe_trigger 失败退避
# ---------------------------------------------------------------------------


def _extractor_with_journal(tmp_path: Path, journal: LearningJournal) -> MemoryExtractor:
    ex = MemoryExtractor(
        session_store=SimpleNamespace(
            get_meta=lambda sid: SimpleNamespace(
                session_id=sid, message_count=50, status="active"
            )
        ),
        llm_client=SimpleNamespace(),
        memory=SimpleNamespace(),
        learning_journal=journal,
        interval_msgs=25,
        cooldown_s=0,
    )
    ex.model_ref = "glm/glm-5.3"
    return ex


def test_maybe_trigger_backs_off_after_recent_failure(tmp_path: Path) -> None:
    journal = LearningJournal(tmp_path / "journal.jsonl", candidate_lookup=None)
    failed = journal.enqueue(
        "memory-extract:s1:25", session_id="s1", source_model="m", kind="memory_extract"
    )
    assert failed is not None
    journal.mark_admitted(failed.job_id)
    journal.mark_started(failed.job_id)
    journal.mark_failed(failed.job_id, "worker_exception")

    ex = _extractor_with_journal(tmp_path, journal)
    assert ex.maybe_trigger("s1") is False  # 近期失败 → 退避，不入队
    from llm_loop.methods.learning_journal import learning_job_id

    assert journal.job(learning_job_id("memory-extract:s1:50")) is None


def test_maybe_trigger_enqueues_when_no_recent_failure(tmp_path: Path) -> None:
    journal = LearningJournal(tmp_path / "journal.jsonl", candidate_lookup=None)
    ex = _extractor_with_journal(tmp_path, journal)
    assert ex.maybe_trigger("s1") is True  # 无失败 → 正常入队
    from llm_loop.methods.learning_journal import learning_job_id

    assert journal.job(learning_job_id("memory-extract:s1:50")) is not None


# ---------------------------------------------------------------------------
# Fix 3: LearningPlane.model_override
# ---------------------------------------------------------------------------


def _plane(tmp_path: Path, *, model_override: str = "") -> tuple[LearningPlane, dict]:
    calls: dict[str, str] = {}

    def resolver(source_model: str):
        calls["resolved"] = source_model
        return SimpleNamespace()

    plane = LearningPlane(
        journal=LearningJournal(tmp_path / "j.jsonl", candidate_lookup=None),
        episode_store=SimpleNamespace(),
        method_store=SimpleNamespace(),
        engine=SimpleNamespace(),
        model_resolver=resolver,
        resource_governor=SimpleNamespace(),
        resource_target_resolver=lambda m: ("glm", m),
        model_override=model_override,
    )
    return plane, calls


def test_plane_model_override_replaces_source_model(tmp_path: Path) -> None:
    plane, calls = _plane(tmp_path, model_override="glm/glm-5.3-flash")
    client = plane._resolve_model("glm/glm-5.3")
    assert client is not None
    assert calls["resolved"] == "glm/glm-5.3-flash"


def test_plane_without_override_keeps_source_model(tmp_path: Path) -> None:
    plane, calls = _plane(tmp_path, model_override="")
    plane._resolve_model("glm/glm-5.3")
    assert calls["resolved"] == "glm/glm-5.3"


# ---------------------------------------------------------------------------
# Fix 1: 工作区激活装配步（learning 分支与 task 公共路径共用）
# ---------------------------------------------------------------------------


def test_activate_default_workspace_mounts_engine(tmp_path: Path, monkeypatch) -> None:
    """learning 引擎必须在提前 return 前激活同一工作区（分桶一致 → owner key 一致）."""
    from llm_loop.factory import _activate_default_workspace

    monkeypatch.chdir(tmp_path)  # 注册的工作区 = 当前目录（隔离）
    calls: list[tuple[str, object]] = []
    engine = SimpleNamespace(
        set_workspace=lambda path, ws_id=None: calls.append((str(path), ws_id)),
        workspace_root="",
        session=SimpleNamespace(),
    )
    settings = SimpleNamespace(data_dir=str(tmp_path / "data"))

    _activate_default_workspace(engine, settings)

    assert calls, "必须调用 engine.set_workspace（learning 分桶缺失即事故根因）"
    assert getattr(engine, "workspace_store", None) is not None
    # 激活后引擎工作区根 = 注册的当前工作区路径
    path, _ = calls[0]
    assert path == str(tmp_path)
