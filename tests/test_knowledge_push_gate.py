"""推送知识资产闸回归测试（RULE-AI-28 push 闸新增层，2026-11-09）。

背景：``data/methods/*/METHOD.md`` 与 ``experiences/*.md`` 在 .gitignore 里是入库
例外，但此前没有任何 gate 提过它们——卡片只活在生成它的那台机器的工作区，换机、
清工作区或新 clone 即静默丢失。闸落在已激活的 ``.githooks/pre-push``
（``core.hooksPath=.githooks``），与既有隐私扫描同层判定。

本测试固化三条行为契约：

1. 有未入库卡 → 拒（exit 1 + 可操作提示），且不依赖真实 ref 行：知识闸是**工作区**
   层面的判定，不该因为「这次推的是哪个提交」而改变；
2. 入库后 → 放行：闸不是恒拒，否则会逼出 ``--no-verify`` 这种绕过习惯；
3. 闸脚本缺失 → fail-closed 拒：看不见的闸等于没有闸（RULE-AI-35）。
"""

import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".githooks" / "pre-push"
FLUSH = REPO_ROOT / "scripts" / "knowledge_flush.py"
UPSTREAM = "https://github.com/deyi2026/llm-first-loop.git"

# 卡片入库阈值（knowledge_flush.MIN_CARD_BYTES=40）：样本须超过它，
# 否则会被当成「过小卡」跳过，测出来的是阈值而不是闸。
CARD_BODY = "# 探针卡\n" + "这是用于回归测试的临时方法卡正文，需要超过四十字节的入库阈值。" * 2


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """临时仓库：复制被测钩子与其依赖的 flush 脚本，隔离真实仓库状态。"""
    r = tmp_path / "repo"
    (r / ".githooks").mkdir(parents=True)
    (r / "scripts").mkdir()
    shutil.copy2(HOOK, r / ".githooks" / "pre-push")
    shutil.copy2(FLUSH, r / "scripts" / "knowledge_flush.py")
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "base.txt").write_text("base\n", encoding="utf-8")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "base", "--no-verify")
    return r


def _run_hook(repo: Path, stdin: str = "") -> subprocess.CompletedProcess:
    """空 stdin 不进 per-ref 隐私扫描循环，把知识闸的行为单独隔离出来。"""
    return subprocess.run(
        ["bash", str(repo / ".githooks" / "pre-push"), "origin", UPSTREAM],
        cwd=repo,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )


def _make_card(repo: Path, rel: str) -> Path:
    card = repo / rel
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(CARD_BODY, encoding="utf-8")
    return card


def test_blocks_untracked_method_card(repo: Path) -> None:
    """未入库方法卡必须拦住推送，并给出修复命令而不是只报错。"""
    _make_card(repo, "data/methods/card-a/METHOD.md")
    out = _run_hook(repo)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "未入库的知识资产" in out.stderr
    assert "knowledge_flush.py" in out.stderr


def test_blocks_untracked_experience_card(repo: Path) -> None:
    """经验卡与方法卡同属知识资产，不得只拦一类。"""
    _make_card(repo, "experiences/EXPERIENCE-20261109-probe.md")
    out = _run_hook(repo)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "未入库的知识资产" in out.stderr


def test_passes_when_clean(repo: Path) -> None:
    """干净工作区必须放行——闸不能把每次推送都卡住。"""
    out = _run_hook(repo)
    assert out.returncode == 0, out.stdout + out.stderr


def test_passes_after_flush(repo: Path) -> None:
    """入库后放行：先证明拦得住，再证明拦得对（不是恒拒）。"""
    _make_card(repo, "data/methods/card-b/METHOD.md")
    assert _run_hook(repo).returncode == 1, "前置条件失败：未入库卡应先被拦住"

    flush = subprocess.run(
        ["python3", str(repo / "scripts" / "knowledge_flush.py")],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )
    assert flush.returncode == 0, flush.stdout + flush.stderr
    assert _run_hook(repo).returncode == 0, "入库后仍被拦：闸变成了恒拒"


def test_fail_closed_when_gate_script_missing(repo: Path) -> None:
    """闸脚本缺失必须拒推：无法判定 ≠ 通过。"""
    (repo / "scripts" / "knowledge_flush.py").unlink()
    out = _run_hook(repo)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "知识闸脚本缺失" in out.stderr


# --- EVO-20261109-b1dad92e P4: flush 也尊重 lane 主写门 ---
def _lane_row(status: str, owner: str, *, minutes_ago: float = 0.0, **extra) -> dict:
    ts = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    row = {
        "lane_id": "lane-probe",
        "branch": "feat/probe",
        "worktree": "/nonexistent",
        "goal_id": "GOAL-T",
        "owner_session_id": owner,
        "status": status,
        "closing_since": ts,
        "last_activity": ts,
    }
    row.update(extra)
    return row


def _ledger(repo: Path, rows: list[dict]) -> None:
    path = repo / "data/audit/lanes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _run_flush(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(repo / "scripts" / "knowledge_flush.py"), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
        encoding="utf-8",
        errors="replace",
    )


def test_flush_uses_latest_lane_version(repo: Path) -> None:
    """append-only 账本：同一 lane 的旧 open 行不得盖过新 closed 行（2026-11-09 实测）。"""
    _make_card(repo, "data/methods/card-g/METHOD.md")
    row_open = _lane_row("open", "sess-other")
    row_open["lane_id"] = "lane-selftest-guard"
    row_open["version"] = 1
    row_closed = _lane_row("closed", "sess-other")
    row_closed["lane_id"] = "lane-selftest-guard"
    row_closed["version"] = 2
    _ledger(repo, [row_open, row_closed])
    out = _run_flush(repo)
    assert out.returncode == 0, out.stdout + out.stderr


def test_flush_blocked_while_other_lane_live(repo: Path) -> None:
    """有他人 live lane → 内部 commit 提前拒绝，不把知识卡写进提交后才发现推不出去。"""
    _make_card(repo, "data/methods/card-c/METHOD.md")
    _ledger(repo, [_lane_row("verifying", "sess-other")])
    out = _run_flush(repo)
    assert out.returncode != 0, out.stdout + out.stderr
    assert "他人 live lane" in out.stderr
    # 闸的承诺是「拦住」，不是「写一半」：卡片仍在工作区，hook 仍然拒推
    assert _run_hook(repo).returncode == 1


def test_flush_allows_own_lane(repo: Path) -> None:
    _make_card(repo, "data/methods/card-d/METHOD.md")
    _ledger(repo, [_lane_row("verifying", "sess-me")])
    out = _run_flush(repo, "--session-id", "sess-me")
    assert out.returncode == 0, out.stdout + out.stderr
    assert _run_hook(repo).returncode == 0, "自己的 lane 被误判为他人"


def test_flush_reclaims_stale_clean_lane(repo: Path, tmp_path: Path) -> None:
    """空闲超时 + worktree 干净 → 按失效回收（与命令闸同口径的保守子集）。"""
    clean = tmp_path / "clean"
    clean.mkdir()
    _git(clean, "init", "-q", "-b", "main")
    _git(clean, "config", "user.email", "t@example.com")
    _git(clean, "config", "user.name", "t")
    (clean / "x.txt").write_text("x\n", encoding="utf-8")
    _git(clean, "add", ".")
    _git(clean, "commit", "-q", "-m", "x")
    _make_card(repo, "data/methods/card-e/METHOD.md")
    _ledger(
        repo,
        [_lane_row("active", "sess-other", minutes_ago=300, worktree=str(clean))],
    )
    out = _run_flush(repo)
    assert out.returncode == 0, out.stdout + out.stderr


def test_flush_fail_closed_on_corrupt_ledger(repo: Path) -> None:
    _make_card(repo, "data/methods/card-f/METHOD.md")
    path = repo / "data/audit/lanes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json\n", encoding="utf-8")
    out = _run_flush(repo)
    assert out.returncode != 0
    assert "lane 账本" in out.stderr


# --- EVO-20261109-b1dad92e P5: hook 扫描回执占位 ---
def test_hook_blocks_placeholder_receipt(repo: Path) -> None:
    receipt = repo / "docs/governance/receipts/merge-probe.md"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text("| main_sha_after | 待回填 |\n", encoding="utf-8")
    out = _run_hook(repo)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "回执" in out.stderr and "待回填" in out.stderr


def test_hook_allows_backfilled_receipt(repo: Path) -> None:
    receipt = repo / "docs/governance/receipts/merge-probe.md"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text("| main_sha_after | 4866ffa36 |\n", encoding="utf-8")
    out = _run_hook(repo)
    assert out.returncode == 0, out.stdout + out.stderr

