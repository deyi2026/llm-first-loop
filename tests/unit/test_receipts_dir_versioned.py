"""docs/receipts/ 落点契约：回执必须落在未被忽略的目录。

背景（2026-11-10 用户决定）：旧落点 docs/promotion/receipts/ 被 .git/info/exclude
的 `docs/promotion/` 整目录规则遮住，git add 静默收不进、漏加不报错，回执只留本机。
新落点 docs/receipts/ 必须始终处于「未被忽略」状态，否则同一类 fail-silent 会复发。

分工：pre-push 负责「写了没入库」的推送前阻断；本测试负责「目录被 ignore 规则
重新遮住」的回归警报。两者合起来把静默丢失变成显式失败。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_RECEIPT_DIR = "docs/receipts"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=_ROOT, capture_output=True, text=True, check=False
    )


def test_receipt_dir_and_readme_exist() -> None:
    assert (_ROOT / _RECEIPT_DIR).is_dir(), f"{_RECEIPT_DIR} 缺失：回执必须有正式落点"
    assert (_ROOT / _RECEIPT_DIR / "README.md").is_file(), (
        f"{_RECEIPT_DIR}/README.md 缺失：落点规则与归档关系须随仓库分发"
    )


def test_receipt_dir_is_not_gitignored() -> None:
    # check-ignore 退出码：0=命中忽略，1=未命中，其它=git 自身异常。
    # --no-index 连已跟踪文件也判定，否则 README 本身被 tracked 会掩盖规则命中。
    probe = f"{_RECEIPT_DIR}/README.md"
    result = _git("check-ignore", "-v", "--no-index", probe)
    assert result.returncode == 1, (
        f"{probe} 被 ignore 规则命中，回执会静默收不进历史：\n"
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_receipt_dir_belongs_to_this_repo() -> None:
    top = _git("rev-parse", "--show-toplevel")
    assert top.returncode == 0, f"git 不可用，无法判定回执落点：{top.stderr}"
    assert Path(top.stdout.strip()).resolve() == _ROOT.resolve(), (
        "测试根与 git 仓库根不一致：回执落点判定可能跑在错误的工作树"
    )
