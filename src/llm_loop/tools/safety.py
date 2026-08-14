"""灾难性安全硬边界 CatastrophicGuard（design.md §2.1.3.5 机制四 / FR-SAFE）.

唯一允许程序硬阻断的边界（FR-SAFE-01）: 只拦截不可逆删除/系统破坏，
其余一切如实反馈放行（FR-SAFE-03）。边界刻意保持极小（FR-SAFE-03）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BlockDecision:
    """一次灾难性阻断判定结果."""

    blocked: bool
    reason: str = ""
    evidence: str = ""  # 判定依据（FR-SAFE-02 阻断信息透明）


# 不可逆删除 / 系统破坏的最小灾难性模式集合（design.md §2.1.3.5）
_CATASTROPHIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # rm -rf 指向根 / 用户主目录 / 系统关键目录
    (
        "rm -rf 指向根目录或系统关键目录",
        re.compile(
            r"rm\s+(-[a-z]*r[a-z]*f[a-z]*|-f[a-z]*r[a-z]*|-[a-z]*rf)\s+(\/\s*$|~\/?\s*$|/(etc|boot|usr|bin|sbin|lib|var|home)(\s|/|$))",
            re.IGNORECASE,
        ),
    ),
    # 格式化 / 建文件系统
    ("mkfs/format 格式化磁盘", re.compile(r"(mkfs\.|mkfs\s|format\s+[a-z]:|newfs)", re.IGNORECASE)),
    # dd 写块设备
    ("dd 写入块设备", re.compile(r"dd\b[^|;]*\bof=/dev/(sd|hd|vd|nvme|disk)", re.IGNORECASE)),
    # fork bomb
    ("fork bomb", re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;", re.IGNORECASE)),
    # curl/wget 管道直连执行
    ("curl/wget 下载直连执行", re.compile(r"(curl|wget)[^|;]*\|\s*(ba)?sh\b", re.IGNORECASE)),
    # 写系统关键区
    (
        "写入系统关键区",
        re.compile(
            r"(>\s*|>>\s*|tee\s+)/etc/(passwd|shadow|sudoers|fstab|hosts|crontab)|(>\s*|>>\s*)//boot",
            re.IGNORECASE,
        ),
    ),
]


class CatastrophicGuard:
    """灾难性行为判定与硬阻断（FR-SAFE 系列）."""

    def guard(self, tool_name: str, args: dict) -> BlockDecision | None:
        """对工具调用做灾难性判定.

        Args:
            tool_name: 工具名.
            args: 工具参数（如 execute_command 的 command 字段）.

        Returns:
            BlockDecision(blocked=True) 命中灾难性模式；
            None 未命中（放行）。
        """
        command = ""
        if tool_name == "execute_command":
            command = str(args.get("command", "") or "")
        elif tool_name in {"delete_file", "write_file", "edit_file", "append_file"}:
            path = str(args.get("path", "") or "")
            command = f"{tool_name} {path}"
        if not command.strip():
            return None

        for label, pattern in _CATASTROPHIC_PATTERNS:
            m = pattern.search(command)
            if m:
                return BlockDecision(
                    blocked=True,
                    reason=f"检测到灾难性行为: {label}。该行为可能造成不可逆破坏，已硬阻断（FR-SAFE-01）。",
                    evidence=f"命令: {command[:200]}; 命中模式: {m.group(0)[:80]}",
                )
        return None


# ── EVO-20260810-2549e9b6: EXEC_MODE 只读命令判定 ──
_READONLY_PREFIXES = (
    "ls",
    "cat",
    "pwd",
    "echo",
    "head",
    "tail",
    "grep",
    "find",
    "which",
    "git status",
    "git log",
    "git diff",
    "ps",
    "df",
    "du",
    "env",
    "date",
    "whoami",
    "python3 -c",
    "python -c",
    "printenv",
)
_WRITE_MARKERS = (
    ">",
    ">>",
    "tee",
    "rm ",
    "mv ",
    "cp ",
    "mkdir",
    "touch",
    "chmod",
    "chown",
    "curl -o",
    "wget -O",
    "pip install",
    "pip3 install",
    "npm install",
    "git add",
    "git commit",
    "git push",
    "git reset",
    "git checkout",
    "source ",
    "export ",
    "unset ",
    "kill",
    "sudo ",
    "brew install",
    "cargo install",
)


def is_readonly_command(command: str) -> bool:
    """判定命令是否只读（EXEC_MODE=readonly 时放行只读，拦截写类）."""
    cmd = command.strip().lstrip()
    if not cmd:
        return False
    if cmd.startswith(_READONLY_PREFIXES):
        # 只读命令 + 无写标记 → 放行
        return not any(m in command for m in _WRITE_MARKERS)
    return False


def link_shaped_paths(path: str | Path) -> list[str]:
    """路径链中的符号链接组件（自身或任一父目录，T5b 对齐 Harness Unlink 模式）.

    路径可不存在（写场景的待建文件）：从最深现有祖先向下检查每层 is_symlink。
    解析失败如实返回空（fail-open，不阻断正常路径）。

    Returns: 含符号链接的路径字符串列表（根 → 叶顺序）；空 = 无链接。
    """
    out: list[str] = []
    try:
        p = Path(path).expanduser()
        # 从最深现有祖先开始（不存在部分先暂存，之后逐层拼回）
        cur = p
        missing: list[Path] = []
        while not cur.exists() and cur != cur.parent:
            missing.append(cur)
            cur = cur.parent
        chain: list[Path] = []
        if cur.exists():
            parts = cur.parts
            probe = Path(parts[0])
            chain.append(probe)
            for part in parts[1:]:
                probe = probe / part
                chain.append(probe)
        for m in reversed(missing):
            chain.append(m)
        for c in chain:
            if c.is_symlink():
                out.append(str(c))
    except OSError:
        pass  # 路径解析失败 fail-open：如实返回已收集结果（不阻断正常路径）
    return out
