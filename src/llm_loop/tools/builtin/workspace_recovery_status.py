"""workspace_recovery_status：工作树搬迁(prebackup)只读观测工具（P0-E1）.

回答四个问题（父会话/子代理只读消费，配套 scripts/restore_prebackup.sh）：
1. 最近一次工作树搬迁备份在哪（backup_dir）、何时创建（created_at）；
2. 备份里有什么（artifacts_present）与被搬走多少（file_counts，从 status.txt
   数 M/??）；
3. 当前 HEAD 是否与备份时的 head.txt 一致（head_matches_prebackup）；
4. 现在如何恢复（restore_cmds：T1 只读检查 / T2 应用 tracked / T3 解包
   untracked，可直接粘贴）。

机械边界（程序所有，语义归模型）：
- 纯只读：不写任何文件、不改 git 状态、不执行恢复；git 一律走
  ``--no-optional-locks``（只读观测不碰 index 锁）；
- 输入双形态：备份元数据优先取 LATEST.json（有则以它为准，derived=false）；
  没有时从 legacy 产物推导（目录 mtime 当 created_at），显式标
  ``derived=true`` + ``retro=true``——推导值不是管线原话，是消费端回推；
- 发现顺序：LFL_PREBACKUP_LATEST_JSON（默认 /tmp/lfl-prebackup-LATEST.json）
  > 指针文件 LFL_PREBACKUP_LATEST_TXT（默认 /tmp/lfl-prebackup-LATEST.txt）
  > 围栏根下 lfl-prebackup* 目录 mtime 最新者（默认根 /tmp/lfl-prebackup* 与
  <repo>/.git/lfl-prebackup/；LFL_PREBACKUP_ROOTS 冒号分隔可整体替换，测试用）；
- 找不到任何备份 → 如实报告 found=false：**没有备份 ≠ 没有做过搬迁**（备份可能
  已被清理/轮转，或落在授权根之外），绝不伪报 0 指标（file_counts/created_at
  等一律 null，仅 current_dirty_count 是当前真实测量）；
- 非 git 目录 / git 不可用 → 确定性 FAILURE 说明缺口，不伪造观测；
- 只回路径、计数与命令，不回显文件内容。
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolResult, ToolResultStatus

SCHEMA_VERSION = 1
_ARTIFACTS = (
    "SHA256SUMS",
    "status.txt",
    "tracked.patch",
    "untracked.tgz",
    "untracked.list.z",
    "head.txt",
    "ahead-behind.txt",
)
_GIT_TIMEOUT_S = 15
_NO_BACKUP_NOTE = "没有备份 ≠ 没有做过搬迁：备份可能已被清理/轮转，或落在授权根之外"


def _git(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "--no-optional-locks", "-C", repo, *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {proc.stderr.strip()[:200]}")
    return proc.stdout


def _env_path(name: str, default: str) -> str:
    return str(os.environ.get(name, "") or default)


def _candidate_roots(repo_root: str) -> list[str]:
    """发现根：LFL_PREBACKUP_ROOTS 优先（测试隔离），否则默认双根（只读 glob）."""
    env = str(os.environ.get("LFL_PREBACKUP_ROOTS", "") or "")
    if env:
        return [r for r in (p.strip() for p in env.split(":")) if r]
    roots: list[str] = []
    for p in sorted(Path("/tmp").glob("lfl-prebackup*")):
        if p.is_dir():
            roots.append(str(p))
    nested = Path(repo_root) / ".git" / "lfl-prebackup"
    if nested.is_dir():
        for p in sorted(nested.iterdir()):
            if p.is_dir():
                roots.append(str(p))
    return roots


def _read_json(path: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _find_backup(repo_root: str) -> dict[str, Any]:
    """发现备份（纯只读）。返回 found/backup_dir/source/derived/retro/created_at."""
    latest_json = _env_path("LFL_PREBACKUP_LATEST_JSON", "/tmp/lfl-prebackup-LATEST.json")
    if os.path.isfile(latest_json):
        data = _read_json(latest_json)
        bdir = str(data.get("backup_dir", "") or "")
        if bdir and os.path.isdir(bdir):
            return {
                "found": True,
                "backup_dir": bdir,
                "source": "latest_json",
                "derived": False,
                "retro": False,
                "created_at": str(data.get("created_at", "") or "") or None,
            }
    ptr = _env_path("LFL_PREBACKUP_LATEST_TXT", "/tmp/lfl-prebackup-LATEST.txt")
    if os.path.isfile(ptr):
        try:
            line = Path(ptr).read_text(encoding="utf-8").splitlines()[-1].strip()
        except (OSError, IndexError):
            line = ""
        if line.startswith("{"):
            line = str(_read_json_line(line))
        if line.startswith("/") and os.path.isdir(line):
            return _legacy_entry(line, "latest_txt_pointer")
    best: tuple[float, str] | None = None
    for root in _candidate_roots(repo_root):
        cands = [root]
        p = Path(root)
        if p.is_dir() and not p.name.startswith("lfl-prebackup"):
            cands = [str(c) for c in sorted(p.glob("lfl-prebackup*")) if c.is_dir()]
        for cand in cands:
            try:
                mtime = os.path.getmtime(cand)
            except OSError:
                continue
            if best is None or mtime > best[0]:
                best = (mtime, cand)
    if best is not None:
        return _legacy_entry(best[1], "newest_by_mtime")
    return {"found": False, "backup_dir": None, "source": None,
            "derived": None, "retro": None, "created_at": None}


def _read_json_line(line: str) -> str:
    try:
        data = json.loads(line)
    except ValueError:
        return ""
    return str(data.get("backup_dir", "") or "") if isinstance(data, dict) else ""


def _legacy_entry(backup_dir: str, source: str) -> dict[str, Any]:
    inner = Path(backup_dir) / "LATEST.json"
    if inner.is_file():
        data = _read_json(str(inner))
        created = str(data.get("created_at", "") or "")
        if created:
            return {"found": True, "backup_dir": backup_dir, "source": f"{source}+inner_latest_json",
                    "derived": False, "retro": False, "created_at": created}
    try:
        mtime = os.path.getmtime(backup_dir)
        created = datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        created = None
    return {"found": True, "backup_dir": backup_dir, "source": source,
            "derived": True, "retro": True, "created_at": created}


def _parse_status_txt(backup_dir: str) -> dict[str, int] | None:
    path = Path(backup_dir) / "status.txt"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    counts = {"modified": 0, "untracked": 0, "other": 0}
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        code = line[:2]
        if line.startswith("??"):
            counts["untracked"] += 1
        elif "M" in code:
            counts["modified"] += 1
        else:
            counts["other"] += 1
    return counts


def _restore_cmds(backup_dir: str) -> tuple[list[str], str]:
    """T1/T2/T3 可直接粘贴命令 + 脚本路径说明（找不到脚本时用占位符并注明）."""
    script = Path(__file__).resolve().parents[4] / "scripts" / "restore_prebackup.sh"
    if script.is_file():
        s = str(script)
        note = ""
    else:
        s = "<llm-first-loop-repo>/scripts/restore_prebackup.sh"
        note = "（脚本未随本安装存在，路径为占位：请到 llm-first-loop 仓库根执行）"
    cmds = [
        f"# T1 只读检查（不写任何文件）\nbash {s} --dir {backup_dir} --check",
        f"# T2 应用 tracked.patch（失败即中止，不留半应用状态）\nbash {s} --dir {backup_dir} --tracked-only",
        f"# T3 解包 untracked（同名不同内容不覆盖，写 <backup_dir>/restored/）\n"
        f"bash {s} --dir {backup_dir} --untracked-only",
    ]
    return cmds, note


class WorkspaceRecoveryStatusTool:
    name = "workspace_recovery_status"
    description = (
        "只读观测工作树搬迁(prebackup)恢复面：最新备份目录与创建时间"
        "（有 LATEST.json 以它为准，否则从 legacy 产物推导并标 derived/retro）、"
        "artifacts_present、status.txt 的 M/?? 文件计数、head_matches_prebackup"
        "（备份 head.txt vs 当前 HEAD）、当前脏文件数、可直接粘贴的 T1/T2/T3 恢复命令。"
        "何时用: 搬迁/恢复前后确认'备份在哪、能否恢复、当前树多脏、HEAD 是否还是备份时的'。"
        "何时不用: 实际执行恢复（用 scripts/restore_prebackup.sh）；跨机器/远端备份"
        "（只看本机围栏根）。边界: 纯只读零副作用；没有备份时如实报告 found=false"
        "——没有备份 ≠ 没有做过搬迁，不伪报 0 指标。"
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "repo_path": {
                "type": "string",
                "description": "待观测的 git 仓库路径（缺省=当前工作目录）。",
            },
        },
        "additionalProperties": False,
    }

    def execute(self, **kwargs) -> ToolResult:
        repo = str(kwargs.get("repo_path", "") or os.getcwd())
        if not os.path.isdir(repo):
            return self._fail(f"repo_path 不是目录: {repo}")
        try:
            root = _git(repo, "rev-parse", "--show-toplevel").strip()
            head = _git(repo, "rev-parse", "HEAD").strip()
            dirty = len([ln for ln in _git(repo, "status", "--porcelain").splitlines() if ln.strip()])
        except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
            return self._fail(f"git 只读观测失败（非 git 目录或 git 不可用）: {exc}")
        backup = _find_backup(root)
        lines = [
            "[workspace_recovery_status] 工作树搬迁恢复面只读观测"
            "（纯只读：不写文件、不改 git 状态、不执行恢复）",
            f"- repo: {root}  HEAD: {head[:12]}…  current_dirty_count: {dirty}",
        ]
        if not backup["found"]:
            summary = {
                "schema_version": SCHEMA_VERSION,
                "found": False,
                "backup_dir": None,
                "created_at": None,
                "derived": None,
                "retro": None,
                "source": None,
                "file_counts": None,
                "head_matches_prebackup": "unavailable",
                "current_dirty_count": dirty,
                "artifacts_present": {},
                "restore_cmds": [],
                "note": _NO_BACKUP_NOTE,
            }
            lines.append(f"- 备份: 未找到（roots={_roots_desc(root)}）")
            lines.append(f"- 边界: {_NO_BACKUP_NOTE}；本报告不伪报 0 指标（file_counts/created_at=null）。")
            lines.append(json.dumps(summary, ensure_ascii=False))
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="\n".join(lines),
                tool_call_id="",
                tool_name=self.name,
            )
        bdir = str(backup["backup_dir"])
        artifacts = {name: (Path(bdir) / name).exists() for name in _ARTIFACTS}
        file_counts = _parse_status_txt(bdir)
        head_match = self._head_match(bdir, head)
        cmds, cmd_note = _restore_cmds(bdir)
        derived_tag = (
            f"derived={backup['derived']} retro={backup['retro']}"
            "（无 LATEST.json：created_at 由目录 mtime 推导，非管线原话）"
            if backup["derived"] else "derived=false（LATEST.json 为准）"
        )
        lines.append(f"- 备份: found=true source={backup['source']} backup_dir={bdir}")
        lines.append(f"  created_at={backup['created_at']}  {derived_tag}")
        lines.append("- artifacts_present: " + ", ".join(
            f"{k}={'yes' if v else 'no'}" for k, v in artifacts.items()))
        if file_counts is None:
            lines.append("- file_counts(status.txt): unavailable（缺 status.txt，不伪报 0）")
        else:
            lines.append(
                f"- file_counts(status.txt): modified={file_counts['modified']}"
                f" untracked={file_counts['untracked']} other={file_counts['other']}")
        lines.append(f"- head_matches_prebackup: {head_match}")
        lines.append(f"- restore_cmds（可直接粘贴{cmd_note}）:")
        for cmd in cmds:
            lines.append(f"    {cmd}")
        lines.append("- 边界: 没有备份 ≠ 没有做过搬迁；恢复动作请用上述脚本，本工具不执行恢复。")
        summary = {
            "schema_version": SCHEMA_VERSION,
            "found": True,
            "backup_dir": bdir,
            "created_at": backup["created_at"],
            "derived": backup["derived"],
            "retro": backup["retro"],
            "source": backup["source"],
            "file_counts": file_counts,
            "head_matches_prebackup": head_match,
            "current_dirty_count": dirty,
            "artifacts_present": artifacts,
            "restore_cmds": [c.splitlines()[-1] for c in cmds],
        }
        lines.append(json.dumps(summary, ensure_ascii=False))
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="\n".join(lines),
            tool_call_id="",
            tool_name=self.name,
        )

    def _head_match(self, bdir: str, head: str) -> str:
        path = Path(bdir) / "head.txt"
        try:
            recorded = path.read_text(encoding="utf-8").strip()
        except OSError:
            return "unavailable"
        recorded = recorded.split()[0] if recorded else ""
        if not recorded:
            return "unavailable"
        return "true" if recorded == head else "false"

    def _fail(self, content: str) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[workspace_recovery_status] {content}",
            tool_call_id="",
            tool_name=self.name,
        )


def _roots_desc(repo_root: str) -> str:
    env = str(os.environ.get("LFL_PREBACKUP_ROOTS", "") or "")
    if env:
        return f"LFL_PREBACKUP_ROOTS={env}"
    return "/tmp/lfl-prebackup* 与 <repo>/.git/lfl-prebackup/"
