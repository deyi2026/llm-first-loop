"""Path Registry: 路径事实登记（正帧 + 负帧 + TTL），防反复搜索 + 快速定位.

EVO-20260823-12be9cac 程序层（路径使用优化三层联动之一）。
三层文件事实:
- L1 git 秒查层（git ls-files，跟踪文件 O(1) 存在性）
- L2 索引加速层（本模块正帧: 存在 + mtime/size/kind，查询时 stat 对账保证新鲜）
- L3 否定帧层（本模块负帧: 不存在路径 TTL 24h，防反复求证）

原理:
- 负帧: read_file/edit_file 失败时登记"该路径不存在"，后续引用回执内嵌提示→停止搜索
- 正帧: 工具命中（read/edit/search）时登记存在 + 元数据；查询走 stat 对账
- 核心: 不追求"全量实时更新"（必然漂移），追求"查询时保证新鲜"——
  query_path 对真实文件做 O(1) stat；负帧仅作提示/检索抑制，不覆盖磁盘真相。

设计约束:
- fail-open: 登记/查询失败绝不阻断主流程（工具真实回执永远是第一事实源）
- workspace 隔离: registry 文件随 current_workspace_root 动态切换；路径键统一为工作区绝对路径
- 零前缀影响: 登记是后台 IO 落盘, 不注入任何消息; 回执提示为固定模板
- TTL: 否定帧 24h 过期（文件可能后来被创建, 不永久盲区）；精确查询仍 stat 复核
- 膨胀控制: 每工作区 ≤200 条, 超限按过期/更新时间淘汰最早
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# 非 None 时仅作为测试/显式覆盖；默认路径必须随当前 workspace 动态计算，不能模块级缓存。
_REGISTRY_PATH: Path | None = None
_TTL_S = 24 * 3600
_MAX_ENTRIES = 200
_LOADED: dict | None = None
_LOADED_PATH: Path | None = None
_LOCK = threading.RLock()


def _registry_file() -> Path:
    if _REGISTRY_PATH is not None:
        return _REGISTRY_PATH
    try:
        from llm_loop.core.run_context import workspace_base

        return Path(workspace_base()) / "data" / "path_registry.json"
    except Exception as exc:  # noqa: BLE001 — 上层 _load/_save fail-open 承接
        # R9-IMM-02（D6）: workspace_base 不可用时禁止静默落入相对路径 "data/"
        # （cwd=仓库根时即真实 data/，测试隔离洞与数据污染根因）。fail-open 保护
        # "登记/查询失败不阻断主流程"，不保护"写入落点"的路径决策（MOVE-CONTROL 面）。
        raise RuntimeError("workspace_base unavailable; refusing implicit data/ fallback") from exc


def _normalize_path(path: str) -> str:
    """把用户/工具路径统一为当前工作区绝对路径（不 resolve symlink，保留路径形状）."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        try:
            from llm_loop.core.run_context import workspace_base

            p = Path(workspace_base()) / p
        except Exception:  # noqa: BLE001 — fail-open
            pass
    return os.path.abspath(str(p))


def _load(*, force: bool = False) -> dict:
    global _LOADED, _LOADED_PATH
    p = _registry_file()
    if not force and _LOADED is not None and p == _LOADED_PATH:
        return _LOADED
    try:
        if p.exists():
            loaded = json.loads(p.read_text(encoding="utf-8"))
            _LOADED = loaded if isinstance(loaded, dict) else {}
        else:
            _LOADED = {}
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("path_registry 读取失败（fail-open）", exc_info=True)
        _LOADED = {}
    _LOADED_PATH = p
    return _LOADED


def _save() -> None:
    global _LOADED
    try:
        p = _LOADED_PATH or _registry_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_LOADED or {}, ensure_ascii=False, indent=1)
        # 原子替换避免任何读者看到半写 JSON；跨进程事务锁由 _mutate 包住 RMW 全段。
        tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(p)
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("path_registry 写入失败（fail-open）", exc_info=True)


@contextmanager
def _file_lock(path: Path):
    """跨进程排他锁；锁文件稳定存在，保护 read-modify-write 整个事务。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    fh = lock_path.open("a+")
    try:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except ImportError:
            # 非 POSIX 平台退化为进程内 RLock；当前生产目标 macOS/Linux 有 fcntl。
            logger.warning("path_registry 平台无 fcntl，跨进程锁退化为进程内锁")
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            logger.debug("path_registry flock unlock 跳过（平台不支持或句柄已释放）")
        fh.close()


def _mutate(mutator) -> None:
    """以最新磁盘快照执行一次跨进程安全的 registry 修改。"""
    with _LOCK:
        p = _registry_file()
        with _file_lock(p):
            reg = _load(force=True)
            mutator(reg)
            _evict_if_needed(reg)
            _save()


def _evict_if_needed(reg: dict) -> None:
    if len(reg) <= _MAX_ENTRIES:
        return
    excess = len(reg) - _MAX_ENTRIES
    for k in sorted(
        reg,
        key=lambda key: reg[key].get("expires_at", reg[key].get("ts", 0)),
    )[:excess]:
        reg.pop(k, None)


def register_missing(path: str, *, source: str = "tool") -> None:
    """登记路径不存在（否定事实帧）."""
    try:
        key = _normalize_path(path)
        now = time.time()

        def _apply(reg: dict) -> None:
            reg[key] = {
                "exists": False,
                "ts": now,
                "expires_at": now + _TTL_S,
                "source": source,
            }

        _mutate(_apply)
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("register_missing 失败（fail-open）", exc_info=True)


def register_exists(path: str) -> None:
    """登记路径存在（成功翻转——否定帧失效，文件已被创建）."""
    try:
        key = _normalize_path(path)
        _mutate(lambda reg: reg.pop(key, None))
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("register_exists 失败（fail-open）", exc_info=True)


def register_seen(
    path: str,
    *,
    mtime: int | None = None,
    size: int | None = None,
    kind: str = "",
) -> None:
    """登记路径存在且带元数据（正帧，索引加速层 L2）."""
    try:
        key = _normalize_path(path)
        now = time.time()

        def _apply(reg: dict) -> None:
            reg[key] = {
                "exists": True,
                "mtime": mtime,
                "size": size,
                "kind": kind,
                "ts": now,
                "source": "tool",
            }

        _mutate(_apply)
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("register_seen 失败（fail-open）", exc_info=True)


def _stat_info(p: Path) -> tuple[os.stat_result, str]:
    st = p.stat()
    kind = "dir" if p.is_dir() else ("file" if p.is_file() else "other")
    return st, kind


def query_path(path: str) -> dict:
    """查询路径事实（始终以当前 workspace 的 stat 为最终真相）.

    返回: {"exists": bool|None, "mtime": int|None, "size": int|None,
           "kind": str, "from": "cache"|"negative_frame"|"stat"|"error"}

    正帧可在 mtime 未变时返回 cache；负帧若文件仍不存在返回 negative_frame，
    但会先做一次 stat，因此外部新建文件不会被 24h 负帧锁死。
    """
    try:
        with _LOCK:
            key = _normalize_path(path)
            p = Path(key)
            reg = _load()
            now = time.time()
            rec = reg.get(key)

            if rec and rec.get("exists") is False and rec.get("expires_at", 0) > now:
                try:
                    st, kind = _stat_info(p)
                except OSError:
                    return {
                        "exists": False,
                        "mtime": None,
                        "size": None,
                        "kind": "",
                        "from": "negative_frame",
                    }
                register_seen(key, mtime=st.st_mtime_ns, size=st.st_size, kind=kind)
                return {
                    "exists": True,
                    "mtime": st.st_mtime_ns,
                    "size": st.st_size,
                    "kind": kind,
                    "from": "stat",
                }

            if rec and rec.get("exists") is True and rec.get("mtime") is not None:
                try:
                    st, kind = _stat_info(p)
                    if st.st_mtime_ns == rec.get("mtime"):
                        return {
                            "exists": True,
                            "mtime": rec.get("mtime"),
                            "size": rec.get("size"),
                            "kind": rec.get("kind", kind),
                            "from": "cache",
                        }
                except OSError:
                    register_missing(key, source="tool:query.stat")
                    return {
                        "exists": False,
                        "mtime": None,
                        "size": None,
                        "kind": "",
                        "from": "stat",
                    }

            try:
                st, kind = _stat_info(p)
                register_seen(key, mtime=st.st_mtime_ns, size=st.st_size, kind=kind)
                return {
                    "exists": True,
                    "mtime": st.st_mtime_ns,
                    "size": st.st_size,
                    "kind": kind,
                    "from": "stat",
                }
            except OSError:
                register_missing(key, source="tool:query.stat")
                return {
                    "exists": False,
                    "mtime": None,
                    "size": None,
                    "kind": "",
                    "from": "stat",
                }
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("query_path 失败（fail-open）", exc_info=True)
        return {"exists": None, "mtime": None, "size": None, "kind": "", "from": "error"}


def check_known_missing(path: str) -> bool:
    """该路径是否已登记不存在且未过期（仅提示事实，不替代 query_path 的 stat）."""
    try:
        with _LOCK:
            reg = _load()
            rec = reg.get(_normalize_path(path))
            if not rec:
                return False
            if rec.get("expires_at", 0) < time.time():
                return False
            return rec.get("exists") is False
    except Exception:  # noqa: BLE001 — fail-open
        return False


def known_missing_note(path: str) -> str:
    """失败回执追加段: 已登记不存在 → 提示停止重复搜索（固定模板）."""
    if check_known_missing(path):
        return (
            "\n[路径登记] 该路径此前已登记不存在（依据工具失败回执, TTL 24h）——"
            "建议停止该路径搜索, 改用 search_files 定位或向用户求证; 若文件刚被创建请重新 read 确认。"
        )
    return ""


def reset() -> None:
    """清空当前工作区登记表（测试/调试用）."""
    global _LOADED, _LOADED_PATH
    with _LOCK:
        p = _registry_file()
        try:
            with _file_lock(p):
                _LOADED = {}
                _LOADED_PATH = p
                if p.exists():
                    p.unlink()
        except Exception:  # noqa: BLE001 — fail-open
            logger.warning("path_registry reset 失败（fail-open）", exc_info=True)
