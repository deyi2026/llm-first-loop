"""推送知识资产告警回归测试（RULE-AI-28 push 闸新增层，2026-11-09；EVO-20261125-e802c5c8 P0）。

背景：``data/methods/*/METHOD.md`` 与 ``experiences/*.md`` 在 .gitignore 里是入库
例外，但此前没有任何 gate 提过它们——卡片只活在生成它的那台机器的工作区，换机、
清工作区或新 clone 即静默丢失。判定落在已激活的 ``.githooks/pre-push``
（``core.hooksPath=.githooks``），与既有隐私扫描同层。

2026-11-09 至 11-25 的实现是「工作区有任何未入库卡即拒推、判定异常也拒推」，实测把
无关会话的知识债务记在每次代码推送头上，推送恒拒。本测试现在固化的行为契约是：

1. 有未入库卡 → **放行**，并给结构化非阻塞告警（单行可机读的
   ``[pre-push][warn] knowledge_flush_pending blocking=false cards=… experiences=…
   other=… pending=…``）+ 修复指引。判定仍是**工作区**层面的，不因「这次推的哪个
   提交」而改变；「纯删除远端 ref」的推送（不携带任何提交/文件，
   EVO-20261123-d43138fc）连告警都不出——混入任何内容 refspec 即恢复告警；
2. 入库后 → 放行且无告警：告警不是恒有的，否则会训练出忽略习惯；
3. 闸脚本缺失/崩溃 → 放行 + ``knowledge_flush_scan_unavailable`` 告警：闸已不挡路，
   看不见的后果只是少一条告警，故不再 fail-closed 拒推；
4. P0 只动知识闸——隐私扫描与回执占位闸不变，仍是硬拒绝（应拦输入实测）。
"""

import json
import os
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


def test_warns_on_untracked_method_card_without_blocking(repo: Path) -> None:
    """未入库方法卡：放行，并给结构化告警 + 修复指引（P0 前在这里拒推）。"""
    _make_card(repo, "data/methods/card-a/METHOD.md")
    out = _run_hook(repo)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "未入库的知识资产" in out.stderr
    assert "knowledge_flush.py" in out.stderr
    assert "拒绝" not in out.stderr
    assert (
        "[pre-push][warn] knowledge_flush_pending blocking=false "
        "cards=1 experiences=0 other=0 pending=1"
    ) in out.stderr


def test_warns_on_untracked_experience_card(repo: Path) -> None:
    """经验卡与方法卡同属知识资产，不得只告警一类。"""
    _make_card(repo, "experiences/EXPERIENCE-20261109-probe.md")
    out = _run_hook(repo)
    assert out.returncode == 0, out.stdout + out.stderr
    assert (
        "[pre-push][warn] knowledge_flush_pending blocking=false "
        "cards=0 experiences=1 other=0 pending=1"
    ) in out.stderr


def test_passes_when_clean(repo: Path) -> None:
    """干净工作区放行且无告警——闸不能把每次推送都卡住，告警也不能每次推送都出现。"""
    out = _run_hook(repo)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "[pre-push][warn]" not in out.stderr


def test_warning_disappears_after_flush(repo: Path) -> None:
    """入库后告警消失：先证明告得对（有卡才告），再证明入库能清掉它。"""
    _make_card(repo, "data/methods/card-b/METHOD.md")
    warned = _run_hook(repo)
    assert warned.returncode == 0 and "knowledge_flush_pending" in warned.stderr, (
        warned.stdout + warned.stderr
    )

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
    after = _run_hook(repo)
    assert after.returncode == 0, after.stdout + after.stderr
    assert "[pre-push][warn]" not in after.stderr, "入库后仍告警：告警清不掉"


def test_warns_when_gate_script_missing(repo: Path) -> None:
    """闸脚本缺失：放行 + scan_unavailable 告警——不伪报干净，也不把工具缺失变成推送故障。"""
    (repo / "scripts" / "knowledge_flush.py").unlink()
    out = _run_hook(repo)
    assert out.returncode == 0, out.stdout + out.stderr
    assert (
        "[pre-push][warn] knowledge_flush_scan_unavailable blocking=false exit=127"
    ) in out.stderr
    assert "手工确认" in out.stderr


def test_warns_when_gate_script_crashes(repo: Path) -> None:
    """闸脚本崩溃（退出码非 0 非 3）与缺失同处置：告警放行。"""
    (repo / "scripts" / "knowledge_flush.py").write_text(
        "raise SystemExit(2)\n", encoding="utf-8"
    )
    out = _run_hook(repo)
    assert out.returncode == 0, out.stdout + out.stderr
    assert (
        "[pre-push][warn] knowledge_flush_scan_unavailable blocking=false exit=2"
    ) in out.stderr


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
    # flush 的承诺是「拦住」，不是「写一半」：卡片仍在工作区、未进任何提交；
    # pre-push 不再因此拒推，但如实告警（卡片只活在本机工作区）。
    hooked = _run_hook(repo)
    assert hooked.returncode == 0 and "knowledge_flush_pending" in hooked.stderr, (
        hooked.stdout + hooked.stderr
    )
    assert (repo / "data/methods/card-c/METHOD.md").exists()


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


# --- EVO-20261123-d43138fc：死 lane 回收 + 纯删 ref 推送豁免知识闸 ---
def test_flush_reclaims_lane_with_missing_worktree(repo: Path) -> None:
    """worktree 已消失（/tmp 被清、worktree 被 prune）→ 物理上已无写者，按失效回收。

    旧行为把 git 失败一律当 live，这种 lane 会永久挡住所有人的 flush 与推送
    （2026-11-23 实测卡住 4 小时）。
    """
    _make_card(repo, "data/methods/card-h/METHOD.md")
    _ledger(
        repo,
        [
            _lane_row(
                "active",
                "sess-gone",
                minutes_ago=300,
                worktree="/nonexistent/worktree/gone-20261123",
            )
        ],
    )
    out = _run_flush(repo)
    assert out.returncode == 0, out.stdout + out.stderr


def test_flush_reclaims_lane_whose_worktree_is_not_a_git_tree(
    repo: Path, dir_outside_any_repo: Path
) -> None:
    """路径还在但已不是 git 工作树（被复用/清空）→ 同样无可写者，按失效回收。"""
    _make_card(repo, "data/methods/card-i/METHOD.md")
    _ledger(
        repo,
        [
            _lane_row(
                "active", "sess-hollow", minutes_ago=300, worktree=str(dir_outside_any_repo)
            )
        ],
    )
    out = _run_flush(repo)
    assert out.returncode == 0, out.stdout + out.stderr


def test_flush_still_blocked_by_stale_dirty_lane(repo: Path, tmp_path: Path) -> None:
    """应拦输入仍拦：空闲超时但 worktree 有未提交改动 → 可能有人正在写，不得回收。"""
    dirty = tmp_path / "dirty"
    dirty.mkdir()
    _git(dirty, "init", "-q", "-b", "main")
    _git(dirty, "config", "user.email", "t@example.com")
    _git(dirty, "config", "user.name", "t")
    (dirty / "x.txt").write_text("x\n", encoding="utf-8")
    _git(dirty, "add", ".")
    _git(dirty, "commit", "-q", "-m", "x")
    (dirty / "x.txt").write_text("uncommitted\n", encoding="utf-8")
    _make_card(repo, "data/methods/card-j/METHOD.md")
    _ledger(repo, [_lane_row("active", "sess-dirty", minutes_ago=300, worktree=str(dirty))])
    out = _run_flush(repo)
    assert out.returncode != 0, out.stdout + out.stderr
    assert "他人 live lane" in out.stderr


def test_hook_allows_delete_only_push_with_untracked_card(repo: Path) -> None:
    """纯删远端 ref 的推送不携带任何提交/文件 → 知识闸豁免。"""
    _make_card(repo, "data/methods/card-k/METHOD.md")
    delete_refs = (
        "(delete) 0000000000000000000000000000000000000000 "
        "refs/heads/gone 1111111111111111111111111111111111111111\n"
    )
    out = _run_hook(repo, stdin=delete_refs)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "跳过知识闸" in out.stdout


@pytest.mark.parametrize("garbled", ["foo bar\n", "(delete)  refs/heads/gone 1111\n"])
def test_hook_does_not_exempt_garbled_refspec(repo: Path, garbled: str) -> None:
    """应拦输入仍拦：refspec 行读不懂（字段缺失/非全零 sha）→ 不豁免，照旧出知识告警。

    是否最终拒推由下游隐私/回执闸决定（fail-closed，非本层职责）；这里只断言知识层
    没有因为读不懂 refspec 就误判成「纯删除」而静默。
    """
    _make_card(repo, "data/methods/card-m/METHOD.md")
    out = _run_hook(repo, stdin=garbled)
    assert "跳过知识闸" not in out.stdout
    assert "[pre-push][warn] knowledge_flush_pending" in out.stderr, out.stdout + out.stderr


def test_hook_warns_on_mixed_push_without_exemption(repo: Path) -> None:
    """删除与内容推送混在一起：不豁免知识判定，照旧出知识告警。"""
    _make_card(repo, "data/methods/card-l/METHOD.md")
    # per-ref 循环会跑隐私扫描：stub 成恒过，把知识告警单独隔离出来
    scan = repo / "scripts" / "git_security_scan.sh"
    scan.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    scan.chmod(0o755)
    tip = _git(repo, "rev-parse", "HEAD").stdout.strip()
    mixed = (
        "(delete) 0000000000000000000000000000000000000000 "
        "refs/heads/gone 1111111111111111111111111111111111111111\n"
        f"refs/heads/main {tip} refs/heads/main {tip}\n"
    )
    out = _run_hook(repo, stdin=mixed)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "跳过知识闸" not in out.stdout
    assert "[pre-push][warn] knowledge_flush_pending" in out.stderr


# --- EVO-20261109-b1dad92e P5: hook 扫描回执占位 ---
def test_hook_blocks_placeholder_receipt(repo: Path) -> None:
    receipt = repo / "docs/governance/receipts/merge-probe.md"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text("| main_sha_after | 待回填 |\n", encoding="utf-8")
    out = _run_hook(repo)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "回执" in out.stderr and "待回填" in out.stderr


def test_hook_still_blocks_placeholder_receipt_with_pending_card(repo: Path) -> None:
    """应拦输入仍拦（P0）：知识告警在场时，回执占位仍是硬拒绝，不被降级成放行。"""
    _make_card(repo, "data/methods/card-p/METHOD.md")
    receipt = repo / "docs/governance/receipts/merge-probe.md"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text("| main_sha_after | 待回填 |\n", encoding="utf-8")
    out = _run_hook(repo)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "待回填" in out.stderr
    assert "[pre-push][warn] knowledge_flush_pending" in out.stderr


def test_hook_still_blocks_privacy_hit_with_pending_card(repo: Path) -> None:
    """应拦输入仍拦（P0）：隐私扫描命中时，知识告警不得把它降级成放行。"""
    _make_card(repo, "data/methods/card-q/METHOD.md")
    scan = repo / "scripts" / "git_security_scan.sh"
    scan.write_text(
        "#!/usr/bin/env bash\necho '模拟隐私扫描命中' >&2\nexit 1\n", encoding="utf-8"
    )
    scan.chmod(0o755)
    tip = _git(repo, "rev-parse", "HEAD").stdout.strip()
    out = _run_hook(repo, stdin=f"refs/heads/main {tip} refs/heads/main {tip}\n")
    assert out.returncode == 1, out.stdout + out.stderr
    assert "模拟隐私扫描命中" in out.stderr


def test_hook_allows_backfilled_receipt(repo: Path) -> None:
    receipt = repo / "docs/governance/receipts/merge-probe.md"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text("| main_sha_after | 4866ffa36 |\n", encoding="utf-8")
    out = _run_hook(repo)
    assert out.returncode == 0, out.stdout + out.stderr


# --- 审查残余②③（2026-11-09 收口）---
@pytest.mark.skipif(os.geteuid() == 0, reason="root 无视权限位，测不出读失败")
def test_hook_fail_closed_on_unreadable_untracked_receipt(repo: Path) -> None:
    """残余②：未跟踪回执读失败（如权限）必须拒推，不再静默按空内容放行。"""
    receipt = repo / "docs/governance/receipts/locked.md"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text("| main_sha_after | 待回填 |\n", encoding="utf-8")
    receipt.chmod(0o000)
    try:
        out = _run_hook(repo)
    finally:
        receipt.chmod(0o644)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "无法读取未跟踪回执" in out.stderr


def test_hook_blocks_renamed_receipt_with_placeholder(repo: Path) -> None:
    """残余③：rename+modify 的回执在 `--diff-filter=AM` 下为空，必须仍被扫到。"""
    # per-ref 循环会跑隐私扫描：stub 成恒过，把回执占位闸单独隔离出来
    scan = repo / "scripts" / "git_security_scan.sh"
    scan.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    scan.chmod(0o755)
    d = repo / "docs/governance/receipts"
    d.mkdir(parents=True)
    # 两行含一行共同内容：rename 检测按行相似度配对（单行全变=0% 不配对，
    # 那是 A/D 而非 R，AM 也能扫到，测不出残余③）
    (d / "old.md").write_text(
        "| main_sha_after | 4866ffa36 |\n"
        "| verify_receipt_id | lane-x:4866ffa3 |\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "receipt-old", "--no-verify")
    _git(repo, "mv", "docs/governance/receipts/old.md", "docs/governance/receipts/new.md")
    (d / "new.md").write_text(
        "| main_sha_after | 待回填 |\n"
        "| verify_receipt_id | lane-x:4866ffa3 |\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "receipt-new", "--no-verify")
    base = _git(repo, "rev-parse", "HEAD~1").stdout.strip()
    tip = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert (
        _git(repo, "diff", "--name-only", "--diff-filter=AM", base, tip).stdout.strip() == ""
    ), "前置条件失败：AM 应漏掉 rename+modify（该行为即残余③）"
    out = _run_hook(repo, stdin=f"refs/heads/main {tip} refs/heads/main {base}\n")
    assert out.returncode == 1, out.stdout + out.stderr
    assert "new.md" in out.stderr and "待回填" in out.stderr

