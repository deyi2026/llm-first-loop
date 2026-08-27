"""Path Registry: 路径事实登记（正帧 + 负帧 + TTL），防反复搜索 + 快速定位.

EVO-20260823-12be9cac 程序层（路径使用优化三层联动之一）。
三层文件事实:
- L1 git 秒查层（git ls-files，跟踪文件 O(1) 存在性）
- L2 索引加速层（本模块正帧: 存在 + mtime/size/kind，查询时 stat 对账保证新鲜）
- L3 否定帧层（本模块负帧: 不存在路径 TTL 24h，防反复求证）

原理:
- 负帧: read_file/edit_file 失败时登记"该路径不存在"，后续引用回执内嵌提示→停止搜索
- 正帧: 工具命中（read/edit/search）时登记存在 + 元数据；查询走 stat 对账
  （mtime 相同→缓存命中 O(1)；不同→刷新登记；不存在→降级负帧）
- 核心: 不追求"全量实时更新"（必然漂移），追求"查询时保证新鲜"——
  stat 是 O(1) 磁盘真相校验，任何时刻查到的都是真的。

设计约束:
- fail-open: 登记/查询失败绝不阻断主流程（工具真实回执永远是第一事实源）
- 零前缀影响: 登记是后台 IO 落盘, 不注入任何消息; 回执提示为固定模板
- TTL: 否定帧 24h 过期（文件可能后来被创建, 不永久盲区）；正帧按 mtime 对账
- 膨胀控制: 每会话 ≤200 条, 超限按过期时间淘汰最早
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_REGISTRY_PATH: Path | None = None
_TTL_S = 24 * 3600        # 否定帧有效期（文件可能后被创建）
_MAX_ENTRIES = 200        # 登记表条目上限（LRU 式淘汰）
_LOADED: dict | None = None


def _registry_file() -> Path:
    global _REGISTRY_PATH
    if _REGISTRY_PATH is None:
        try:
            from llm_loop.core.run_context import workspace_base

            _REGISTRY_PATH = Path(workspace_base()) / "data" / "path_registry.json"
        except Exception:  # noqa: BLE001 — fail-open
            _REGISTRY_PATH = Path("data") / "path_registry.json"
    return _REGISTRY_PATH


def _load() -> dict:
    global _LOADED
    if _LOADED is not None:
        return _LOADED
    try:
        p = _registry_file()
        if p.exists():
            _LOADED = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(_LOADED, dict):
                _LOADED = {}
        else:
            _LOADED = {}
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("path_registry 读取失败（fail-open）", exc_info=True)
        _LOADED = {}
    return _LOADED


def _save() -> None:
    global _LOADED
    try:
        p = _registry_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(_LOADED or {}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("path_registry 写入失败（fail-open）", exc_info=True)


def register_missing(path: str, *, source: str = "tool") -> None:
    """登记路径不存在（否定事实帧）."""
    try:
        reg = _load()
        now = time.time()
        reg[str(path)] = {
            "exists": False,
            "ts": now,
            "expires_at": now + _TTL_S,
            "source": source,
        }
        # 膨胀控制: 超上限按过期时间淘汰最早
        if len(reg) > _MAX_ENTRIES:
            excess = len(reg) - _MAX_ENTRIES
            for k in sorted(reg, key=lambda k: reg[k].get("expires_at", 0))[:excess]:
                reg.pop(k, None)
        _save()
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("register_missing 失败（fail-open）", exc_info=True)


def register_exists(path: str) -> None:
    """登记路径存在（成功翻转——否定帧失效，文件已被创建）."""
    try:
        reg = _load()
        if str(path) in reg:
            reg.pop(str(path), None)
            _save()
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("register_exists 失败（fail-open）", exc_info=True)


def register_seen(path: str, *, mtime: int | None = None, size: int | None = None, kind: str = "") -> None:
    """登记路径存在且带元数据（正帧，索引加速层 L2）.

    工具命中（read/edit/search 成功）时调用；mtime 用于查询对账（新鲜性校验）。
    """
    try:
        reg = _load()
        now = time.time()
        reg[str(path)] = {
            "exists": True,
            "mtime": mtime,
            "size": size,
            "kind": kind,
            "ts": now,
            "source": "tool",
        }
        if len(reg) > _MAX_ENTRIES:
            excess = len(reg) - _MAX_ENTRIES
            for k in sorted(reg, key=lambda k: reg[k].get("ts", 0))[:excess]:
                reg.pop(k, None)
        _save()
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("register_seen 失败（fail-open）", exc_info=True)


def query_path(path: str) -> dict:
    """查询路径事实（查询时 stat 对账，保证新鲜——核心机制）.

    返回: {"exists": bool, "mtime": int|None, "size": int|None, "kind": str, "from": "cache"|"stat"}
    - 缓存命中（正帧且 mtime 未变）→ O(1) 返回，不碰磁盘
    - 缓存过期/未登记 → stat 真实文件（O(1) 真相）：存在→刷新正帧；不存在→降级登记负帧
    任何时刻返回的都是真的（stat 校验），不依赖全量实时更新。
    """
    try:
        p = Path(path).expanduser()
        key = str(p)
        reg = _load()
        now = time.time()
        rec = reg.get(key)
        # 1) 负帧命中且未过期 → 直接判不存在（不碰磁盘，防反复 stat 同一不存在路径）
        if rec and rec.get("exists") is False and rec.get("expires_at", 0) > now:
            return {"exists": False, "mtime": None, "size": None, "kind": "", "from": "negative_frame"}
        # 2) 缓存正帧命中且 mtime 未变 → 缓存即真相
        if rec and rec.get("exists") is True and rec.get("mtime") is not None:
            try:
                st = p.stat()
                if st.st_mtime_ns == rec.get("mtime"):
                    return {
                        "exists": True,
                        "mtime": rec.get("mtime"),
                        "size": rec.get("size"),
                        "kind": rec.get("kind", ""),
                        "from": "cache",
                    }
            except OSError:
                # 缓存说有但 stat 失败（文件已删）→ 降级负帧
                register_missing(key, source="tool:query.stat")
                return {"exists": False, "mtime": None, "size": None, "kind": "", "from": "stat"}
        # 3) 未登记 / 缓存过期 → stat 真相对账
        try:
            st = p.stat()
            kind = "dir" if p.is_dir() else ("file" if p.is_file() else "other")
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
            return {"exists": False, "mtime": None, "size": None, "kind": "", "from": "stat"}
    except Exception:  # noqa: BLE001 — fail-open
        return {"exists": None, "mtime": None, "size": None, "kind": "", "from": "error"}


def check_known_missing(path: str) -> bool:
    """该路径是否已登记不存在且未过期（True=命中否定帧）."""
    try:
        reg = _load()
        rec = reg.get(str(path))
        if not rec:
            return False
        if rec.get("expires_at", 0) < time.time():
            return False  # 过期 → 视为未登记（允许重新验证）
        return rec.get("exists") is False
    except Exception:  # noqa: BLE001 — fail-open
        return False


def known_missing_note(path: str) -> str:
    """失败回执追加段: 已登记不存在 → 提示停止搜索（固定模板, 零前缀影响）."""
    if check_known_missing(path):
        return (
            "\n[路径登记] 该路径此前已登记不存在（依据工具失败回执, TTL 24h）——"
            "建议停止该路径搜索, 改用 search_files 定位或向用户求证; 若文件刚被创建请重新 read 确认。"
        )
    return ""


def reset() -> None:
    """清空登记表（测试/调试用）."""
    global _LOADED
    _LOADED = {}
    try:
        p = _registry_file()
        if p.exists():
            p.unlink()
    except Exception:  # noqa: BLE001 — fail-open
        logger.warning("path_registry reset 失败（fail-open）", exc_info=True)
