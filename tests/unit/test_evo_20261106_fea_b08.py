"""EVO-20261106-fead950b（合并建议卡统一收敛路线提示）与
EVO-20261106-b0806c32（跨会话 EVO 完成待登记暂存/一键落账）回归测试。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from llm_loop.core.run_context import current_session_id
from llm_loop.introspection.merge_queue import MergeQueueStore, build_merge_advice
from llm_loop.introspection.tools_merge_queue import (
    run_lane_merge_advice,
    run_lane_queue_status,
)
from llm_loop.timekeeping import system_local_now

# ---------------- merge queue 夹具（与 test_merge_queue.py 同构） ----------------


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "base")
    return root


@pytest.fixture()
def store(tmp_path: Path, repo: Path) -> MergeQueueStore:
    return MergeQueueStore(tmp_path / "audit", repo_root=str(repo))


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "main")


def _branch_commit(repo: Path, branch: str, rel: str, content: str) -> str:
    _git(repo, "checkout", "-b", branch, "main")
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-m", f"change {rel}")
    sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "main")
    return sha


def _write_receipt(store: MergeQueueStore, receipt_id: str, lane_id: str, base_sha: str) -> None:
    row = {
        "receipt_id": receipt_id,
        "lane_id": lane_id,
        "base_sha": base_sha,
        "result": "pass",
        "created_at": system_local_now().isoformat(),
        "ttl_s": 3600,
    }
    with Path(store.receipts_path).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _enqueue(store: MergeQueueStore, lane_id: str, *, head: str, base: str, paths: list[str]) -> None:
    _write_receipt(store, f"vr-{lane_id}", lane_id, base)
    store.enqueue(
        lane_id=lane_id,
        branch=f"fix/{lane_id}",
        head_sha=head,
        base_main_sha=base,
        paths=paths,
        verify_ref=f"vr-{lane_id}",
    )


class _Host:
    def __init__(self, audit_dir: Path | None, repo_root: Path | None = None) -> None:
        self.audit_dir = str(audit_dir) if audit_dir is not None else None
        self.repo_root = str(repo_root) if repo_root is not None else None
        self.ctx = None


# ---------------- fead950b: 统一收敛路线提示 ----------------


def test_advice_multi_lane_has_route_hint(store: MergeQueueStore, repo: Path) -> None:
    """多 lane → 建议卡带 push_review_route_hint，工具回执摘要带收敛路线。"""
    h0 = _head(repo)
    a = _branch_commit(repo, "fix/a", "src/only_a.py", "a = 1\n")
    b = _branch_commit(repo, "fix/b", "src/only_b.py", "b = 1\n")
    _enqueue(store, "lane-a", head=a, base=h0, paths=["src/only_a.py"])
    _enqueue(store, "lane-b", head=b, base=h0, paths=["src/only_b.py"])

    card = build_merge_advice(store)
    assert len(card["lanes"]) == 2
    hint = card.get("push_review_route_hint")
    assert hint and "merge --no-ff" in hint and "一次整树 push 审查" in hint

    result = run_lane_merge_advice(None, _Host(Path(store.receipts_path).parent, repo), {})
    assert "[收敛路线]" in result.content
    assert "统一一次整树 push 审查" in result.content or "一次整树 push 审查" in result.content


def test_advice_single_lane_no_hint(store: MergeQueueStore, repo: Path) -> None:
    """单 lane → 不出现提示（不噪音）。"""
    h0 = _head(repo)
    a = _branch_commit(repo, "fix/a", "src/only_a.py", "a = 1\n")
    _enqueue(store, "lane-a", head=a, base=h0, paths=["src/only_a.py"])
    card = build_merge_advice(store)
    assert "push_review_route_hint" not in card
    result = run_lane_merge_advice(None, _Host(Path(store.receipts_path).parent, repo), {})
    assert "[收敛路线]" not in result.content


def test_queue_status_stale_hint(store: MergeQueueStore, repo: Path) -> None:
    """有 stale 项 → queue_status 摘要带统一收敛提示。"""
    h0 = _head(repo)
    a = _branch_commit(repo, "fix/a", "src/only_a.py", "a = 1\n")
    _enqueue(store, "lane-a", head=a, base=h0, paths=["src/only_a.py"])
    # main 前进 → base 过期 → stale
    (repo / "README.md").write_text("main moved\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "main moved")
    result = run_lane_queue_status(None, _Host(Path(store.receipts_path).parent, repo), {})
    assert "stale×1" in result.content
    assert "整树 push 审查" in result.content
    # 无 stale 时不出现
    fresh = build_merge_advice(store)  # advice 不受影响，仅验证 queue 摘要逻辑
    assert fresh["main_head"] != h0


# ---------------- b0806c32: 完成待登记暂存 + 一键落账 ----------------


def _make_engine(tmp_path):
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        self_inspection_enabled=False,
        extract_enabled=False,
    )
    return build_engine(settings)  # type: ignore[no-any-return]


def _stage_executing(engine, sid: str):
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="跨会话演进", impact_scope="tools", session_id=sid)
    store.review(sug.id, "accepted")
    store.transition(sug.id, status="executing")
    return store, sug


def test_cross_session_denial_stages_handoff(tmp_path):
    """跨会话登记被拒 → 生成暂存条目 + coordination 可见。"""
    engine = _make_engine(tmp_path)
    store, sug = _stage_executing(engine, "owner-session")

    tok = current_session_id.set("other-session")
    try:
        r = engine.corrections.execute(
            "evolution_complete",
            {"suggestion_id": sug.id, "note": "实现完成", "actions": ["commit abc123"]},
        )
    finally:
        current_session_id.reset(tok)
    assert r.status.value == "failure"
    assert "跨会话归属拒绝" in r.content
    assert "完成待登记" in r.content

    from llm_loop.introspection.evolution_handoff import load_completion_handoff

    entry = load_completion_handoff(store.dir, sug.id)
    assert entry is not None
    assert entry["owner_session"] == "owner-session"
    assert entry["implementing_session"] == "other-session"
    assert entry["actions"] == ["commit abc123"]

    # coordination 聚合可见
    from llm_loop.introspection.goal_coordination import (
        coordination_snapshot,
        render_coordination,
    )

    snap = coordination_snapshot(str(store.dir), session_id="owner-session")
    ids = [h.get("suggestion_id") for h in snap.get("evolution_completion_handoffs") or []]
    assert sug.id in ids
    rendered = render_coordination(snap)
    assert "完成待登记" in rendered and sug.id in rendered


def test_owner_consumes_handoff_one_shot(tmp_path):
    """owner 会话重调（不带 actions）→ 自动取用暂存参数并清除条目。"""
    engine = _make_engine(tmp_path)
    store, sug = _stage_executing(engine, "owner-session")

    # 执行会话先被拒（暂存）
    tok = current_session_id.set("other-session")
    try:
        engine.corrections.execute(
            "evolution_complete",
            {"suggestion_id": sug.id, "note": "实现完成", "actions": ["commit abc123", "commit def456"]},
        )
    finally:
        current_session_id.reset(tok)

    # owner 一键落账：只给 suggestion_id + note（无 actions）
    tok = current_session_id.set("owner-session")
    try:
        r = engine.corrections.execute(
            "evolution_complete", {"suggestion_id": sug.id, "note": "归属复核后落账"}
        )
    finally:
        current_session_id.reset(tok)
    assert r.status.value == "success"
    assert "一键落账" in r.content

    exec_log = (engine.settings.audit_dir / "evolution_exec_log.jsonl").read_text(encoding="utf-8")
    assert "commit abc123" in exec_log and "commit def456" in exec_log

    from llm_loop.introspection.evolution_handoff import load_completion_handoff

    assert load_completion_handoff(store.dir, sug.id) is None


def test_owner_own_actions_also_clears(tmp_path):
    """owner 自带 actions → 不取用暂存，但成功后仍清条目（防僵尸）。"""
    engine = _make_engine(tmp_path)
    store, sug = _stage_executing(engine, "owner-session")
    from llm_loop.introspection.evolution_handoff import stage_completion_handoff

    stage_completion_handoff(
        store.dir,
        suggestion_id=sug.id,
        owner_session="owner-session",
        implementing_session="other-session",
        actions=["staged-only"],
    )
    tok = current_session_id.set("owner-session")
    try:
        r = engine.corrections.execute(
            "evolution_complete",
            {"suggestion_id": sug.id, "note": "自证后落账", "actions": ["my own action"]},
        )
    finally:
        current_session_id.reset(tok)
    assert r.status.value == "success"
    exec_log = (engine.settings.audit_dir / "evolution_exec_log.jsonl").read_text(encoding="utf-8")
    assert "my own action" in exec_log and "staged-only" not in exec_log

    from llm_loop.introspection.evolution_handoff import load_completion_handoff

    assert load_completion_handoff(store.dir, sug.id) is None
