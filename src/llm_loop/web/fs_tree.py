"""文件树 + 会话树 API（EVO-20260818 DSH 064，用户需求左侧栏树状对齐）.

A. 文件树: GET /api/v1/fs/tree（目录+文件，单层可展）+ 文件操作
   （POST mkdir / PUT rename / DELETE 两步令牌确认）
B. 会话树: GET /api/v1/agents/tree（会话→子代理层级）

安全边界（安全审查与修复建议书 2026-10-25 P0-2/P0-3/S2-7 + preview 越界模式）:
- 所有路径 resolve 后必须仍在工作区根内（is_relative_to 越界拒绝）；
  workspace_root 缺失时不再回退项目根 → 503 workspace_unconfigured（S2-7）
- 路径只接受字面量：含通配元字符（* ? [）直接拒绝；本模块任何端点都
  不对用户输入做 glob/rglob 展开，tree 只做单层 iterdir（S2-7）
- DELETE 两步令牌（P0-2）: 先 GET /api/v1/fs/delete-token 领取一次性
  token（≥24bit 随机，绑定 realpath+调用者身份，TTL 300s，单次使用），
  再带 token+confirm=true 删除；缺 token → 409 confirm_token_required
- 根保护（P0-2/S1-2）: 工作区根本身及其任意父目录/项目根及其祖先/
  家目录及其祖先/文件系统根/_SYSTEM_DIRS 子路径一律拒绝（realpath 后判定）；
  目标或路径组件是符号链接 → 拒绝（逐段 lstat，不依赖 resolve）
- 内部目录保护: .git/.lfs_checkpoints/.trash/.worktrees 命中须 hard=true；
  敏感文件（.env/*.pem/*.key/*_rsa/id_ed25519/credentials* 等）须 hard=true；
  遍历条目数封顶（5000）防 DoS，超限同样须 hard=true
- 操作审计: 普通操作与令牌签发 fail-open（log warning）；删除/重命名等
  破坏性操作 fail-closed——审计写失败 → 拒绝执行并返回明确错误（S2-7）
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import shutil
import stat
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from llm_loop import security_guard
from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)

fs_router = APIRouter()

# 危险路径黑名单（删除/操作须拦截的敏感目标；resolve 后对比）
_DANGEROUS_NAMES = {
    "/",  # 根
    ".",  # 当前
    "..",  # 上级
    ".git",  # 版本库
    "__pycache__",  # 缓存
    "node_modules",  # 依赖（可重建，但常巨大，防误删）
}
_DANGEROUS_ROOT_PATTERNS = ("/System", "/Library", "/etc", "/usr", "/var", "/bin", "/sbin", "/Applications", "/opt")


class WorkspaceUnconfigured(RuntimeError):  # noqa: N818 - 既有公开名，跨 12 处引用，暂不重命名
    """engine.workspace_root 缺失/不可用；fs 端点须返回 503 而非回退项目根（S2-7）."""


def resolve_under_workspace(raw: str, workspace_root: str) -> Path | None:
    """纯函数：把 raw 解析到 workspace_root 之下；越界/非法返回 None.

    - workspace_root 缺失（空串/不存在）→ raise WorkspaceUnconfigured
      （S2-7：旧实现回退项目根，等价把整个代码仓暴露为可操作面；现改为
      显式失败，调用方映射为 503 workspace_unconfigured）
    - 相对路径基于工作区根；绝对路径 resolve 后必须仍在根内
    - 无 engine 依赖、无副作用，供 preview_routes 等后续复用
    """
    root_raw = str(workspace_root or "").strip()
    if not root_raw:
        raise WorkspaceUnconfigured("workspace_root 未配置")
    try:
        root = Path(root_raw).resolve()
        if not root.exists():
            raise WorkspaceUnconfigured(f"workspace_root 不存在: {root}")
        p = Path(raw).expanduser()
        target = p.resolve() if p.is_absolute() else (root / p).resolve()
    except WorkspaceUnconfigured:
        raise
    except (OSError, ValueError, RuntimeError):
        return None  # 含 NUL 等非法输入（S3-7）→ 统一按越界拒绝
    if not target.is_relative_to(root):
        return None
    return target


def _resolve_under_root(raw: str, engine: Any) -> Path | None:
    """解析路径并确保在工作区根内；越界/非法返回 None，未配置抛 WorkspaceUnconfigured."""
    return resolve_under_workspace(raw, str(getattr(engine, "workspace_root", "") or ""))


def _unconfigured_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": "workspace_unconfigured",
            "detail": "工作区未配置（workspace_root 缺失或不存在）；已禁止回退项目根。",
        },
    )


# S2-7: 本模块不接受任何 pattern；含通配元字符的路径直接拒绝（绝不 glob 展开）。
# 现状核实：fs_tree 端点只做单层 iterdir，本模块本就无 rglob/glob 调用；
# 此处把"只接受字面量"固化为显式契约，防止未来引入模式展开时退化为全仓递归枚举。
_GLOB_META_CHARS = ("*", "?", "[")


def _contains_glob_meta(raw: str) -> bool:
    return any(ch in raw for ch in _GLOB_META_CHARS)


def _is_dangerous(target: Path) -> bool:
    """危险路径判定: 黑名单名 + 敏感根模式."""
    name = target.name
    if name in _DANGEROUS_NAMES:
        return True
    s = str(target)
    return any(s.startswith(p) for p in _DANGEROUS_ROOT_PATTERNS)


def _append_audit_entry(engine: Any, action: str, detail: str) -> None:
    """审计条目落盘（失败向上抛，由调用方决定 fail-open / fail-closed）."""
    base = Path(getattr(engine.settings, "audit_dir", None) or "./data/audit")
    base.mkdir(parents=True, exist_ok=True)
    with (base / "fs_operations.jsonl").open("a", encoding="utf-8") as f:
        entry = {
            "ts": system_local_now().isoformat(),
            "action": action,
            "detail": detail,
        }
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _audit(request: Request, action: str, detail: str) -> None:
    """非破坏性操作审计（fail-open，不阻断操作；令牌签发同此）."""
    try:
        _append_audit_entry(_engine_from(request), action, detail)
    except Exception:  # noqa: BLE001 — 审计失败不阻断（非破坏性路径）
        logger.warning("fs 操作审计失败（fail-open）: %s %s", action, detail)


def _audit_destructive(request: Request, action: str, detail: str) -> bool:
    """破坏性操作审计（S2-7 fail-closed）：写失败返回 False，调用方必须拒绝执行.

    在执行破坏性操作 *之前* 写入（审计先行：即使进程在操作中途死亡，
    审计已存在；操作随后失败只是多记一次尝试，方向安全）。
    """
    try:
        _append_audit_entry(_engine_from(request), action, detail)
        return True
    except Exception as exc:  # noqa: BLE001 — 破坏性操作必须 fail-closed
        logger.error(
            "fs 破坏性操作审计写入失败（fail-closed，拒绝执行）: %s %s: %s",
            action, detail, exc,
        )
        return False


def _engine_from(request: Request):
    # 与 routes.py _engine_from 同模式：应用状态持有 engine
    return request.app.state.engine


# ── P0-2 删除保护：根/符号链接/内部目录/敏感文件 ──
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # 代码仓根

try:  # 系统目录黑名单复用工具层常量（realpath 后比较）
    from llm_loop.tools.safety import _SYSTEM_DIRS
except Exception:  # pragma: no cover - 兜底集合与 safety.py 保持一致
    _SYSTEM_DIRS = ("/etc", "/boot", "/usr", "/bin", "/sbin", "/lib", "/var", "/home")

# 递归删除受保护目录（命中须 hard=true）
# R2-1（红队第二轮 #1）：macOS/Windows 大小写不敏感文件系统上 `.TRASH`/`.Git`
# 可绕过精确匹配——一律先 lower() 再比较（同名集本身全小写）。
_PROTECTED_DIR_NAMES = {".git", ".lfs_checkpoints", ".trash", ".worktrees"}
# 敏感文件名（命中须 hard=true）
_SENSITIVE_EXACT_NAMES = {".env", "id_ed25519", "id_rsa", "id_ecdsa", "id_dsa"}
_SENSITIVE_NAME_SUFFIXES = (".pem", ".key", "_rsa")
_SENSITIVE_NAME_PREFIXES = ("credentials",)
# 删除前扫描条目上限（防遍历 DoS；超限按"无法确认安全"须 hard=true）
_SENSITIVE_SCAN_MAX_ENTRIES = 5000


def _is_sensitive_name(name: str) -> bool:
    n = name.lower()
    return (
        n in _SENSITIVE_EXACT_NAMES
        or n.endswith(_SENSITIVE_NAME_SUFFIXES)
        or n.startswith(_SENSITIVE_NAME_PREFIXES)
    )


def _delete_root_guard_reason(target: Path, engine: Any) -> str | None:
    """realpath 后判定删除目标是否命中根保护；返回原因 key（None=放行）.

    拒绝: 文件系统根 / _SYSTEM_DIRS 及其子路径 / 家目录及其祖先 /
    工作区根本身及其任意祖先 / 项目根及其祖先（P0-2/S1-2）。
    target 须已由 resolve_under_workspace realpath 化。

    豁免: 工作区根本身位于某系统目录子树内时（如 macOS 临时目录在
    /private/var/folders），该子树内的目标不再按 system_dir 拒绝——
    此时工作区包含性检查就是边界；把系统目录本身设为工作区需经
    P0-3 允许根显式授权，属管理员信任决策。
    """
    canonical = target
    fs_root = Path(canonical.anchor) if canonical.anchor else Path("/")
    if canonical == fs_root:
        return "filesystem_root"
    ws_root_raw = str(getattr(engine, "workspace_root", "") or "").strip()
    wr: Path | None = None
    if ws_root_raw:
        try:
            wr = Path(ws_root_raw).resolve()
        except (OSError, ValueError):
            wr = None
    for d in _SYSTEM_DIRS:
        try:
            dr = Path(d).resolve()
        except (OSError, ValueError):
            continue
        if canonical == dr or canonical.is_relative_to(dr):
            if wr is not None and wr.is_relative_to(dr):
                continue  # 工作区位于该系统目录子树内 → 由包含性检查担纲
            return "system_dir"
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        home = None
    if home is not None and (canonical == home or home.is_relative_to(canonical)):
        return "home_or_ancestor"
    if wr is not None and (canonical == wr or wr.is_relative_to(canonical)):
        return "workspace_root_or_ancestor"
    if canonical == _PROJECT_ROOT or _PROJECT_ROOT.is_relative_to(canonical):
        return "project_root_or_ancestor"
    return None


def _lexical_target(raw: str, workspace_root: str) -> Path | None:
    """归一化但 *不* resolve 符号链接的词法路径（供逐段 lstat 判定）."""
    try:
        p = Path(raw).expanduser()
        if p.is_absolute():
            return Path(os.path.normpath(str(p)))
        root = Path(str(workspace_root or "").strip()).resolve()
        return Path(os.path.normpath(str(root / p)))
    except (OSError, ValueError, RuntimeError):
        return None


def _first_symlink_component(lexical: Path) -> Path | None:
    """从文件系统锚点到 lexical 逐段 lstat；返回首个 symlink 组件（含末段）.

    resolve() 会把符号链接"吃掉"，穿越检测不能只靠 resolve（P0-2）：
    必须对用户提供的词法路径逐段 lstat。不存在的尾段跳过（其后段必然
    不存在）；lstat 其它失败按可疑处理（fail-closed）。
    """
    chain = [lexical]
    p = lexical
    while p.parent != p:
        p = p.parent
        chain.append(p)
    for q in reversed(chain):  # 自文件系统根向下逐段
        try:
            st = os.lstat(q)
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            return q  # 无法判定 → fail-closed 视为可疑
        if stat.S_ISLNK(st.st_mode):
            return q
    return None


def _scan_delete_tree(target: Path) -> dict[str, Any]:
    """一次受控遍历同时检测受保护目录与敏感文件（条目封顶防 DoS）.

    返回 {"protected": Path|None, "sensitive": Path|None, "capped": bool}；
    capped=True 表示超过条目上限、无法确认安全性 → 调用方按须 hard=true 拒绝。
    不跟随目录符号链接（symlink 目录不入栈）。
    """
    result: dict[str, Any] = {"protected": None, "sensitive": None, "capped": False}
    if target.name.lower() in _PROTECTED_DIR_NAMES and target.is_dir() and not target.is_symlink():
        result["protected"] = target
    if _is_sensitive_name(target.name):
        result["sensitive"] = target
    if not target.is_dir() or target.is_symlink():
        return result
    limit = _SENSITIVE_SCAN_MAX_ENTRIES  # 函数体内读取，测试可 monkeypatch
    seen = 0
    stack = [target]
    while stack:
        cur = stack.pop()
        try:
            for e in cur.iterdir():
                seen += 1
                if seen > limit:
                    result["capped"] = True
                    return result
                if e.name.lower() in _PROTECTED_DIR_NAMES and e.is_dir() and not e.is_symlink():
                    result["protected"] = result["protected"] or e
                if _is_sensitive_name(e.name):
                    result["sensitive"] = result["sensitive"] or e
                if e.is_dir() and not e.is_symlink():
                    stack.append(e)
        except OSError:
            continue
    return result


# ── P0-2 两步删除令牌（进程内存储 + threading.Lock；重启即失效）──
_DELETE_TOKEN_TTL_SECONDS = 300
_DELETE_TOKENS: dict[str, dict[str, Any]] = {}
_DELETE_TOKENS_LOCK = threading.Lock()


def reset_delete_tokens_for_tests() -> None:
    """测试钩子：清空进程内删除令牌表。仅测试调用，勿接入生产路径。"""
    with _DELETE_TOKENS_LOCK:
        _DELETE_TOKENS.clear()


def _caller_identity(request: Request) -> str:
    """调用者身份指纹: Bearer/会话 cookie 凭据的 sha256 前 8 位；无凭据退回客户端 IP."""
    auth = request.headers.get("authorization") or ""
    if auth[:7].lower() == "bearer ":
        cred = auth[7:].strip()
        if cred:
            digest = hashlib.sha256(cred.encode("utf-8")).hexdigest()[:8]
            return f"bearer:{digest}"
    cookie_name = "lfl_web_session_v2"
    try:
        from llm_loop.web.auth import SESSION_COOKIE_NAME

        cookie_name = SESSION_COOKIE_NAME
    except Exception:  # noqa: BLE001 — 常量兜底，不因 auth 模块演进而失效
        pass
    sid = request.cookies.get(cookie_name, "")
    if sid:
        digest = hashlib.sha256(sid.encode("utf-8")).hexdigest()[:8]
        return f"session:{digest}"
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) or "unknown"
    return f"ip:{host}"


def _prune_expired_locked(now: float) -> None:
    for t in [t for t, e in _DELETE_TOKENS.items() if e["expires_at"] <= now]:
        _DELETE_TOKENS.pop(t, None)


def _issue_delete_token(realpath: str, identity: str) -> str:
    """签发一次性令牌：128bit 随机（≥24bit 要求）；同身份+路径旧令牌即时失效."""
    now = time.time()
    token = secrets.token_hex(16)
    with _DELETE_TOKENS_LOCK:
        # 过期清理 + "同一身份+路径至多 1 个有效令牌"（重复申请使旧 token 失效）
        stale = [
            t
            for t, e in _DELETE_TOKENS.items()
            if e["expires_at"] <= now
            or (e["identity"] == identity and e["realpath"] == realpath)
        ]
        for t in stale:
            _DELETE_TOKENS.pop(t, None)
        _DELETE_TOKENS[token] = {
            "realpath": realpath,
            "identity": identity,
            "expires_at": now + _DELETE_TOKEN_TTL_SECONDS,
        }
    return token


def _peek_delete_token(token: str, realpath: str, identity: str) -> tuple[bool, str]:
    """只读校验（不消费）：存在性/身份/路径/有效期。"""
    now = time.time()
    with _DELETE_TOKENS_LOCK:
        _prune_expired_locked(now)
        entry = _DELETE_TOKENS.get(token)
        if entry is None:
            return False, "令牌不存在或已失效。"
        if entry["identity"] != identity:
            return False, "令牌与调用者身份不匹配。"
        if entry["realpath"] != realpath:
            return False, "令牌绑定的目标路径不一致。"
        return True, ""


def _consume_delete_token(token: str, realpath: str, identity: str) -> tuple[bool, str]:
    """单次消费（原子，锁内复核）：并发重放在此处淘汰。"""
    now = time.time()
    with _DELETE_TOKENS_LOCK:
        entry = _DELETE_TOKENS.get(token)
        if entry is None:
            return False, "令牌不存在、已使用或已失效。"
        if entry["identity"] != identity:
            return False, "令牌与调用者身份不匹配。"
        if entry["realpath"] != realpath:
            return False, "令牌绑定的目标路径不一致。"
        if entry["expires_at"] <= now:
            _DELETE_TOKENS.pop(token, None)
            return False, "令牌已过期。"
        del _DELETE_TOKENS[token]
        return True, ""


# ── P2-4（2026-10-25）：删除回收站 + undo 窗口 ──
# 语义：默认删除 = 移入 <workspace>/.trash/，10 分钟内可用 undo_token 还原；
# hard=true 才是永久删除（仍需两步令牌 + 全部根/符号链接/敏感约束）。
# 诚实边界：这是"误操作缓冲"，不是安全删除——回收站内容仍在磁盘上，
# 物理销毁需 hard=true 或外部工具。
_UNDO_TTL_SECONDS = 600
_TRASH_DIR_NAME = ".trash"
_TRASH_RETENTION_SECONDS = 7 * 24 * 3600
_UNDO_TOKENS: dict[str, dict[str, Any]] = {}
_UNDO_TOKENS_LOCK = threading.Lock()


def reset_undo_tokens_for_tests() -> None:
    """测试钩子：清空进程内 undo 令牌表。仅测试调用，勿接入生产路径。"""
    with _UNDO_TOKENS_LOCK:
        _UNDO_TOKENS.clear()


def _trash_root(engine: Any) -> Path | None:
    root = str(getattr(engine, "workspace_root", "") or "")
    if not root:
        return None
    return Path(root) / _TRASH_DIR_NAME


def _purge_old_trash(trash_root: Path) -> None:
    """尽力清理超过保留期的回收站条目；失败只记日志（不阻断删除主流程）."""
    cutoff = time.time() - _TRASH_RETENTION_SECONDS
    try:
        for entry in trash_root.iterdir():
            if entry.is_symlink():
                continue
            if entry.stat().st_mtime >= cutoff:
                continue
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
    except OSError:
        logger.warning("回收站清理失败（不影响本次删除）: %s", trash_root, exc_info=True)


def _move_to_trash(target: Path, engine: Any) -> tuple[dict[str, Any] | None, str]:
    """把目标移入回收站并签发 undo 令牌；返回 (payload, error_code)."""
    trash_root = _trash_root(engine)
    if trash_root is None:
        return None, "workspace_unconfigured"
    try:
        trash_root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        dest = trash_root / f"{stamp}-{target.name}"
        seq = 1
        while dest.exists():
            dest = trash_root / f"{stamp}-{seq}-{target.name}"
            seq += 1
        # R2-1b（红队第二轮 #1）：回收站目的地处落在删除目标之内（如删除 .trash
        # 自身或其祖先）→ 前置拒绝软删除。自移动既无意义（shutil.move 会失败），
        # 又掩盖"回收站被整体卷走"的真实语义；此处显式拒绝、不产生任何移动。
        try:
            if dest.resolve().is_relative_to(target.resolve()):
                return None, "target_contains_trash_dest"
        except (OSError, ValueError, RuntimeError):
            return None, "target_contains_trash_dest"
        shutil.move(str(target), str(dest))
    except OSError as exc:
        return None, f"trash_failed: {exc}"
    token = secrets.token_hex(16)
    with _UNDO_TOKENS_LOCK:
        now = time.time()
        for t in [t for t, e in _UNDO_TOKENS.items() if e["expires_at"] <= now]:
            _UNDO_TOKENS.pop(t, None)
        _UNDO_TOKENS[token] = {
            "trash": str(dest),
            "original": str(target),
            "expires_at": now + _UNDO_TTL_SECONDS,
        }
    _purge_old_trash(trash_root)
    return {"trash_path": str(dest), "undo_token": token, "expires_in": _UNDO_TTL_SECONDS}, ""


def _consume_undo_token(token: str) -> tuple[dict[str, Any] | None, str]:
    now = time.time()
    with _UNDO_TOKENS_LOCK:
        entry = _UNDO_TOKENS.get(token)
        if entry is None:
            return None, "令牌不存在、已使用或已失效。"
        if entry["expires_at"] <= now:
            _UNDO_TOKENS.pop(token, None)
            return None, "令牌已过期（undo 窗口 10 分钟）。"
        del _UNDO_TOKENS[token]
        return entry, ""


def _peek_undo_token(token: str) -> tuple[dict[str, Any] | None, str]:
    """R2-2（红队第二轮 #2）：只读校验（不消费）。

    restore 的冲突前置检查（trash 缺失 / 原路径已存在）用本函数——冲突时
    不得烧毁 undo token，用户清掉冲突后可用同一 token 重试；成功路径仍在
    执行 move 前由 _consume_undo_token 原子消费（并发重放/双击在此淘汰）。
    """
    now = time.time()
    with _UNDO_TOKENS_LOCK:
        # 先判请求令牌，再清理其余过期项：否则过期令牌会被清理掉，用户只能
        # 看到笼统的"不存在"，无法区分"窗口已过"与"令牌无效/已被使用"。
        entry = _UNDO_TOKENS.get(token)
        if entry is not None and entry["expires_at"] <= now:
            _UNDO_TOKENS.pop(token, None)
            return None, "令牌已过期（undo 窗口 10 分钟）。"
        for t in [t for t, e in _UNDO_TOKENS.items() if e["expires_at"] <= now]:
            _UNDO_TOKENS.pop(t, None)
        if entry is None:
            return None, "令牌不存在、已使用或已失效。"
        return dict(entry), ""


# ── A. 文件树 ──
@fs_router.get("/api/v1/fs/tree")
def fs_tree(request: Request, path: str = "") -> JSONResponse:
    """目录+文件树（单层可展）: 返回指定目录的 dirs+files 列表.

    S2-7: 只做单层 iterdir，绝不对 path 做 glob/rglob 展开；含通配元字符
    （* ? [）的路径直接拒绝（按字面量也无从匹配真实目录，显式拒绝使
    契约清晰、可被测试钉死）。
    """
    if _contains_glob_meta(path):
        return JSONResponse(status_code=400, content={"error": "glob_meta_rejected", "detail": "路径含通配元字符（* ? [）；本端点只接受字面量路径，不做模式展开。"})
    engine = _engine_from(request)
    try:
        target = _resolve_under_root(path, engine)
    except WorkspaceUnconfigured:
        return _unconfigured_response()
    if target is None:
        return JSONResponse(status_code=400, content={"error": "out_of_bounds", "detail": "路径越界或非法。"})
    if not target.is_dir():
        return JSONResponse(status_code=404, content={"error": "dir_not_found", "detail": f"目录不存在: {target}"})
    try:
        dirs, files = [], []
        for p in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if p.name.startswith(".") or p.name == "__pycache__":
                continue
            if p.is_dir():
                dirs.append(p.name)
            elif p.is_file():
                files.append({"name": p.name, "size": p.stat().st_size})
    except OSError as exc:
        return JSONResponse(status_code=403, content={"error": "dir_unreadable", "detail": f"目录不可读: {exc}"})
    return JSONResponse(content={
        "path": str(target),
        "parent": str(target.parent) if target != target.parent else None,
        "dirs": dirs[:500],
        "files": files[:500],
    })


@fs_router.post("/api/v1/fs/mkdir")
def fs_mkdir(request: Request, path: str = "") -> JSONResponse:
    """新建目录（相对工作区根）."""
    if not path.strip():
        return JSONResponse(status_code=400, content={"error": "invalid_path", "detail": "缺少 path。"})
    if _contains_glob_meta(path):
        return JSONResponse(status_code=400, content={"error": "glob_meta_rejected", "detail": "路径含通配元字符（* ? [）；只接受字面量路径。"})
    engine = _engine_from(request)
    try:
        target = _resolve_under_root(path, engine)
    except WorkspaceUnconfigured:
        return _unconfigured_response()
    if target is None or _is_dangerous(target):
        return JSONResponse(status_code=400, content={"error": "invalid_path", "detail": "路径越界或非法。"})
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return JSONResponse(status_code=403, content={"error": "mkdir_failed", "detail": f"创建失败: {exc}"})
    _audit(request, "mkdir", str(target))
    return JSONResponse(content={"status": "created", "path": str(target)})


@fs_router.put("/api/v1/fs/rename")
def fs_rename(request: Request, path: str = "", new_name: str = "") -> JSONResponse:
    """重命名文件/目录（path 为新名的父目录路径或旧路径，new_name 为目标名）."""
    if not path.strip() or not new_name.strip():
        return JSONResponse(status_code=400, content={"error": "invalid_path", "detail": "缺少 path/new_name。"})
    if _contains_glob_meta(path):
        return JSONResponse(status_code=400, content={"error": "glob_meta_rejected", "detail": "路径含通配元字符（* ? [）；只接受字面量路径。"})
    engine = _engine_from(request)
    try:
        target = _resolve_under_root(path, engine)
    except WorkspaceUnconfigured:
        return _unconfigured_response()
    if target is None or _is_dangerous(target):
        return JSONResponse(status_code=400, content={"error": "invalid_path", "detail": "路径越界或非法。"})
    # R2-4（红队第二轮 #4）：with_name 对含路径分隔符（a/b）、"." 等非法新名抛
    # ValueError——此前未捕获直接 500；统一落 400 invalid_path（不执行、不审计）。
    try:
        new_target = target.with_name(new_name.strip())
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_path", "detail": "new_name 非法：不得为空、不得含路径分隔符、不得为 '.'。"},
        )
    try:
        new_resolved = _resolve_under_root(str(new_target), engine)
    except WorkspaceUnconfigured:
        return _unconfigured_response()
    if not new_resolved:
        return JSONResponse(status_code=400, content={"error": "out_of_bounds", "detail": "新路径越界。"})
    # P1-3 补洞（2026-10-25）：敏感文件禁止重命名——`.env` → `.env.example`
    # 曾可把敏感文件洗成模板后缀，绕过 preview 的模板豁免规则读取内容。
    sensitive_reason = security_guard.sensitive_path_reason(target)
    if sensitive_reason:
        return JSONResponse(
            status_code=403,
            content={
                "error": "sensitive_path_blocked",
                "detail": f"敏感路径禁止重命名（{sensitive_reason}）；轮换/改名请人工处理。",
            },
        )
    # S2-7: 重命名是破坏性操作 → 审计 fail-closed（写失败拒绝执行），
    # 且审计先于操作写入。
    if not _audit_destructive(request, "rename", f"{target} → {new_target}"):
        return JSONResponse(status_code=500, content={"error": "audit_write_failed", "detail": "审计写入失败，破坏性操作已拒绝（fail-closed）。"})
    try:
        target.rename(new_target)
    except OSError as exc:
        return JSONResponse(status_code=403, content={"error": "rename_failed", "detail": f"重命名失败: {exc}"})
    return JSONResponse(content={"status": "renamed", "from": str(target), "to": str(new_target)})


@fs_router.get("/api/v1/fs/delete-token")
def fs_delete_token(request: Request, path: str = "") -> JSONResponse:
    """P0-2 第一步：签发一次性删除令牌（绑定 realpath + 调用者身份）.

    返回 {token, expires_in, path}；TTL 300s，单次使用，同一身份+路径
    重复申请使旧令牌失效。受保护根/符号链接目标拒绝签发（删除端点还会
    独立复核，纵深防御）。签发写审计（fail-open，log warning）。
    """
    if not path.strip():
        return JSONResponse(status_code=400, content={"error": "invalid_path", "detail": "缺少 path。"})
    if _contains_glob_meta(path):
        return JSONResponse(status_code=400, content={"error": "glob_meta_rejected", "detail": "路径含通配元字符（* ? [）；只接受字面量路径。"})
    engine = _engine_from(request)
    try:
        target = _resolve_under_root(path, engine)
    except WorkspaceUnconfigured:
        return _unconfigured_response()
    if target is None:
        return JSONResponse(status_code=400, content={"error": "out_of_bounds", "detail": "路径越界或非法。"})
    reason = _delete_root_guard_reason(target, engine)
    if reason is not None:
        return JSONResponse(status_code=409, content={"error": "protected_root", "detail": f"受保护路径（{reason}），拒绝签发删除令牌。"})
    lexical = _lexical_target(path, str(getattr(engine, "workspace_root", "") or ""))
    if lexical is not None and _first_symlink_component(lexical) is not None:
        return JSONResponse(status_code=409, content={"error": "symlink_rejected", "detail": "目标或路径组件是符号链接，拒绝签发删除令牌。"})
    if not target.exists():
        return JSONResponse(status_code=404, content={"error": "file_not_found", "detail": f"目标不存在: {target}"})
    if target.name.lower() in _PROTECTED_DIR_NAMES and target.is_dir() and not target.is_symlink():
        # 提前拒绝，避免签发无意义的令牌（删除端点仍有独立复核）；
        # R2-1：lower 比较——`.TRASH`/`.Git` 等大小写变体同样拒绝签发。
        return JSONResponse(
            status_code=409,
            content={"error": "protected_dir", "detail": f"受保护目录 {target.name}：删除需 hard=true 且仍受根/敏感约束。"},
        )
    identity = _caller_identity(request)
    token = _issue_delete_token(str(target), identity)
    _audit(request, "delete_token_issue", f"path={target} identity={identity} ttl={_DELETE_TOKEN_TTL_SECONDS}")
    return JSONResponse(content={"token": token, "expires_in": _DELETE_TOKEN_TTL_SECONDS, "path": str(target)})


@fs_router.delete("/api/v1/fs/delete")
def fs_delete(request: Request, path: str = "", confirm: bool = False, token: str = "", hard: bool = False) -> JSONResponse:
    """删除文件/目录（不可逆；P0-2 两步令牌 + 根/符号链接/内部目录保护）.

    须同时带 confirm=true 与有效一次性 token（GET /api/v1/fs/delete-token
    领取）；token 绑定签发时 realpath 与调用者身份，TTL 300s，单次使用。
    hard=true 仅豁免内部目录/敏感文件/扫描上限，不豁免根保护、符号链接
    与令牌校验（A/B 全部约束仍生效）。
    """
    if not confirm:
        return JSONResponse(status_code=409, content={"error": "confirm_required", "detail": "删除为不可逆操作，须带 confirm=true 确认。"})
    if not path.strip():
        return JSONResponse(status_code=400, content={"error": "invalid_path", "detail": "缺少 path。"})
    if _contains_glob_meta(path):
        return JSONResponse(status_code=400, content={"error": "glob_meta_rejected", "detail": "路径含通配元字符（* ? [）；只接受字面量路径。"})
    engine = _engine_from(request)
    try:
        target = _resolve_under_root(path, engine)
    except WorkspaceUnconfigured:
        return _unconfigured_response()
    if target is None:
        return JSONResponse(status_code=400, content={"error": "out_of_bounds", "detail": "路径越界或非法，已拒绝。"})
    reason = _delete_root_guard_reason(target, engine)
    if reason is not None:
        return JSONResponse(status_code=409, content={"error": "protected_root", "detail": f"受保护路径（{reason}），拒绝删除。"})
    lexical = _lexical_target(path, str(getattr(engine, "workspace_root", "") or ""))
    if lexical is not None and _first_symlink_component(lexical) is not None:
        return JSONResponse(status_code=409, content={"error": "symlink_rejected", "detail": "目标或路径组件是符号链接，拒绝删除。"})
    if not token:
        return JSONResponse(status_code=409, content={"error": "confirm_token_required", "detail": "删除须两步确认：先 GET /api/v1/fs/delete-token?path=... 领取一次性令牌，再带 token 与 confirm=true 删除。"})
    identity = _caller_identity(request)
    ok, why = _peek_delete_token(token, str(target), identity)
    if not ok:
        return JSONResponse(status_code=409, content={"error": "token_invalid", "detail": why})
    if not target.exists() and not target.is_symlink():
        return JSONResponse(status_code=404, content={"error": "file_not_found", "detail": f"目标不存在: {target}"})
    if not hard:
        scan = _scan_delete_tree(target)
        if scan["protected"] is not None:
            return JSONResponse(status_code=409, content={"error": "protected_dir", "detail": f"目标内含受保护目录（{scan['protected'].name}；.git/.lfs_checkpoints/.trash/.worktrees），须 hard=true。"})
        if scan["sensitive"] is not None:
            return JSONResponse(status_code=409, content={"error": "sensitive_file_requires_hard", "detail": f"目标内含敏感文件（{scan['sensitive'].name}），须 hard=true。"})
        if scan["capped"]:
            return JSONResponse(status_code=409, content={"error": "scan_limit_requires_hard", "detail": f"目标条目数超扫描上限（{_SENSITIVE_SCAN_MAX_ENTRIES}），无法确认不含受保护/敏感内容，须 hard=true。"})
    # S2-7: 审计先行且 fail-closed——审计写不进就绝不执行不可逆删除。
    # 顺序说明：审计失败时令牌尚未消费（用户修复审计后可用同一令牌重试）。
    if not _audit_destructive(request, "delete", f"{target} hard={hard} identity={identity}"):
        return JSONResponse(status_code=500, content={"error": "audit_write_failed", "detail": "审计写入失败，破坏性操作已拒绝（fail-closed）。"})
    # 单次消费（原子，锁内复核）：并发重放在此处淘汰
    ok, why = _consume_delete_token(token, str(target), identity)
    if not ok:
        return JSONResponse(status_code=409, content={"error": "token_invalid", "detail": why})
    if hard:
        try:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        except OSError as exc:
            return JSONResponse(status_code=403, content={"error": "delete_failed", "detail": f"删除失败: {exc}"})
        _audit(request, "delete_hard", f"{target} identity={identity}")
        return JSONResponse(content={"status": "deleted", "path": str(target), "hard": True})

    # P2-4：默认先进回收站，返回 undo_token（10 分钟内可还原）
    payload, err = _move_to_trash(target, engine)
    if payload is None:
        return JSONResponse(
            status_code=403,
            content={"error": "trash_failed", "detail": f"移入回收站失败（未执行不可逆删除）: {err}"},
        )
    _audit(request, "delete_trash", f"{target} -> {payload['trash_path']} identity={identity}")
    return JSONResponse(content={"status": "trashed", "path": str(target), "hard": False, **payload})


@fs_router.post("/api/v1/fs/restore")
def fs_restore(request: Request, token: str = "") -> JSONResponse:
    """P2-4：用 undo_token 把回收站条目还原到原路径（10 分钟窗口，单次使用）."""
    if not token.strip():
        return JSONResponse(status_code=400, content={"error": "token_required", "detail": "缺少 undo_token。"})
    # R2-2（红队第二轮 #2）：冲突检查先行且只读（peek）——冲突时不得消费令牌，
    # 用户清掉冲突后同一 token 可重试；成功路径在 move 前由 _consume 原子消费。
    entry, why = _peek_undo_token(token)
    if entry is None:
        return JSONResponse(status_code=409, content={"error": "undo_token_invalid", "detail": why})
    trash_path = Path(entry["trash"])
    original = Path(entry["original"])
    if not trash_path.exists():
        return JSONResponse(status_code=404, content={"error": "trash_missing", "detail": "回收站条目不存在（可能已被清理）。"})
    if original.exists():
        return JSONResponse(
            status_code=409,
            content={"error": "restore_conflict", "detail": f"原路径已存在，拒绝覆盖: {original}；清理冲突后可用同一 undo_token 重试。"},
        )
    entry, why = _consume_undo_token(token)
    if entry is None:
        return JSONResponse(status_code=409, content={"error": "undo_token_invalid", "detail": why})
    trash_path = Path(entry["trash"])
    original = Path(entry["original"])
    try:
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(trash_path), str(original))
    except OSError as exc:
        return JSONResponse(status_code=403, content={"error": "restore_failed", "detail": f"还原失败: {exc}"})
    _audit(request, "restore", f"{trash_path} -> {original} identity={_caller_identity(request)}")
    return JSONResponse(content={"status": "restored", "path": str(original)})


# ── B. 会话树 ──
# M3 验收后续（agents/tree 源站实测 5-13s）：进程内 TTL 缓存。
# 根因：707 个 subagent 候选 × topology_snapshot → 事件日志恢复
# （EventStore.read 全读+fold）+ 会话 parent 交叉验证；目录面板 1s
# 心跳 × 多标签页持续打满事件循环。命中直接返回缓存
# 响应（不重算）；TTL 过期重算；仅缓存成功（200）
# 响应，list 失败/异常不入缓存（下次调用即重算）。
# JSON 响应字节等价：缓存 payload 为 dict（插入序确定），
# 重包 JSONResponse 序列化字节与首次相同。键控 id(engine)
# 并在值中持有 engine 强引用作身份校验（id 复用不会跨
# engine 串数据；有界 8 条防泄漏，生产进程实际=1 个 engine）。
_AGENTS_TREE_CACHE_TTL_SECONDS = 30.0
_agents_tree_cache_lock = threading.Lock()
_agents_tree_cache: dict[int, tuple[float, object, dict[str, object]]] = {}


def _reset_agents_tree_cache_for_tests() -> None:
    with _agents_tree_cache_lock:
        _agents_tree_cache.clear()


def _agents_tree_cache_get(engine: object) -> dict[str, object] | None:
    with _agents_tree_cache_lock:
        entry = _agents_tree_cache.get(id(engine))
        if entry is None:
            return None
        cached_at, cached_engine, payload = entry
        if cached_engine is not engine:
            return None
        if time.monotonic() - cached_at >= _AGENTS_TREE_CACHE_TTL_SECONDS:
            return None
        return payload


def _agents_tree_cache_put(engine: object, payload: dict[str, object]) -> None:
    with _agents_tree_cache_lock:
        _agents_tree_cache[id(engine)] = (time.monotonic(), engine, payload)
        while len(_agents_tree_cache) > 8:
            _agents_tree_cache.pop(next(iter(_agents_tree_cache)))


@fs_router.get("/api/v1/agents/tree")
def agents_tree(request: Request) -> JSONResponse:
    """会话→子代理层级树（对齐 DSH agents 树）.

    数据源: Session.parent_id + subagent_ 前缀会话（runner 创建）。
    返回: [{id, status, model, parent_id, activity?, outcome?, settlement?}]，前端按 parent_id 组树。
    activity/outcome/settlement 只来自 engine.subagent_runner.topology_snapshot 的机械
    事实；runner 缺失或拓扑未知时字段缺省——不伪造 inactive。
    """
    engine = _engine_from(request)
    cached_payload = _agents_tree_cache_get(engine)
    if cached_payload is not None:
        return JSONResponse(content=cached_payload)
    topology = getattr(engine, "subagent_runner", None)
    try:
        metas = engine.session.list_sessions()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": "list_failed", "detail": f"会话列表失败: {exc}"})
    # 2026-09-22 CPU 契约修复：节点字段全部来自 SessionMeta（同一解析缓存），
    # 不再逐会话全量 load（460 会话/324MB 时每请求 2.2s CPU，1s 心跳 ×
    # 多标签页即饱和事件循环）。topology 事实仍按 sid 附着，语义不变。
    nodes = []
    for meta in metas:
        sid = meta.session_id
        try:
            parent_id = getattr(meta, "parent_id", None)
            is_subagent = str(sid).startswith("subagent_")
            node = {
                "id": sid,
                "parent_id": parent_id,
                "is_subagent": is_subagent,
                "model": getattr(meta, "model_override", None) or "",
                "created_at": getattr(meta, "created_at", None),
            }
            # 2026-09-23 run 期间 100% CPU 终诊：topology_snapshot → 事件日志
            # 恢复，对全部会话执行 = 0.25-5.7s/请求（随日志增长）。根会话
            # （无 parent 且非 subagent_ 前缀）的 facts 本来就是 None——只对
            # 子代理候选调用，输出零变化。
            if topology is not None and (is_subagent or parent_id):
                # 以 topology 事实源为权威：非 runner 子会话（如 fork 分支）自然返回
                # None → 不附着 activity；不依赖 sid 前缀做二次推断。
                facts = topology.topology_snapshot(sid)
                if facts:
                    node["activity"] = "running" if facts.get("local_active") else "inactive"
                    node["outcome"] = str(facts.get("outcome") or "")
                    node["settlement"] = str(facts.get("settlement_state") or "")
            nodes.append(node)
        except Exception:  # noqa: BLE001 — 单会话拓扑附着失败跳过（节点仍返回）
            nodes.append({"id": sid, "parent_id": getattr(meta, "parent_id", None)})
    payload: dict[str, object] = {"nodes": nodes}
    _agents_tree_cache_put(engine, payload)
    return JSONResponse(content=payload)
