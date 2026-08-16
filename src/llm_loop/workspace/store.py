"""工作区注册表（对齐 DSH Workspace：目录绑定、会话按工作区分区隔离）.

- 注册表文件: data/workspaces.json（version + workspaces[{id, path, created_at}]）
- workspace key（会话目录名）: DSH 式路径编码 `--Users-yyj-Project-llm-first-loop--`
  （绝对路径 / → -，剥前导 /，首尾 --）
- 会话存储: data/sessions/<key>/<session_id>.json（按工作区分区）
- 迁移: 首次装配把 data/sessions 下旧会话（非目录文件）移入默认工作区目录（幂等）
- 安全: create 校验路径为存在的目录 + 绝对路径规范化；remove 仅注销注册不删数据
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_REGISTRY_NAME = "workspaces.json"
_REGISTRY_VERSION = 1


def workspace_key(path: str | Path) -> str:
    """绝对路径 → 会话目录名（DSH 式编码：/Users/a/b → --Users-a-b--）."""
    p = Path(path).resolve()
    return "--" + str(p).lstrip("/").replace("/", "-") + "--"


@dataclass
class Workspace:
    """一个工作区条目（目录绑定；id 可读、key 唯一）."""

    path: str  # 规范化绝对路径
    created_at: str = ""
    id: str = ""  # 默认 = workspace_key(path)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = workspace_key(self.path)


class WorkspaceStore:
    """工作区注册表（fail-open 加载；原子写保存）."""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._data_dir / _REGISTRY_NAME
        self._workspaces: dict[str, Workspace] = {}
        self._current_id: str = ""
        self._load()

    # ── 读取 ──
    def _load(self) -> None:
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
            for w in raw.get("workspaces", []):
                path = str(w.get("path", "")).strip()
                if not path:
                    continue
                ws = Workspace(path=path, created_at=str(w.get("created_at", "")), id=str(w.get("id", "")))
                self._workspaces[ws.id] = ws
            self._current_id = str(raw.get("current", ""))
        except FileNotFoundError:
            pass  # 首次启动无注册表 → 空
        except Exception as exc:  # noqa: BLE001 — 损坏注册表 fail-open 空加载
            logger.warning("工作区注册表加载失败（fail-open）: %s", exc)

    def _save(self) -> None:
        tmp = self._file.with_suffix(".json.tmp")
        payload = {
            "version": _REGISTRY_VERSION,
            "current": self._current_id,
            "workspaces": [
                {"id": w.id, "path": w.path, "created_at": w.created_at}
                for w in self._workspaces.values()
            ],
        }
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._file)
        except OSError as exc:
            logger.warning("工作区注册表保存失败（fail-open）: %s", exc)

    def list(self) -> list[Workspace]:
        return list(self._workspaces.values())

    def get(self, ws_id: str) -> Workspace | None:
        return self._workspaces.get(ws_id)

    def get_current(self) -> Workspace | None:
        return self._workspaces.get(self._current_id)

    def sessions_root(self, data_dir: str | Path) -> Path:
        """当前工作区会话目录（data/sessions/<key>）."""
        base = Path(data_dir) / "sessions"
        current = self.get_current()
        if current is None:
            return base
        return base / current.id

    # ── 变更 ──
    def register(self, path: str | Path) -> Workspace:
        """注册工作区（路径须为存在的目录；已注册幂等返回既有条目）."""
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            raise ValueError(f"工作区路径不是存在的目录: {p}")
        key = workspace_key(p)
        existed = self._workspaces.get(key)
        if existed is not None:
            return existed
        ws = Workspace(path=str(p), created_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self._workspaces[ws.id] = ws
        self._save()
        logger.info("工作区注册: %s", ws.path)
        return ws

    def switch(self, ws_id: str) -> Workspace:
        """切换当前工作区（未注册 → ValueError）."""
        ws = self._workspaces.get(ws_id)
        if ws is None:
            raise ValueError(f"工作区未注册: {ws_id}")
        self._current_id = ws_id
        self._save()
        return ws

    def remove(self, ws_id: str) -> bool:
        """注销工作区（不删会话数据；当前工作区不可注销）."""
        if ws_id == self._current_id:
            return False
        if ws_id not in self._workspaces:
            return False
        del self._workspaces[ws_id]
        self._save()
        return True

    # ── 迁移（旧单根会话 → 默认工作区）──
    def migrate_legacy_sessions(self, data_dir: str | Path, default_workspace: Workspace) -> int:
        """把 data/sessions/ 下旧版单根会话文件移入默认工作区目录（幂等）.

        返回迁移文件数。仅当默认工作区目录尚无文件时执行（防重复迁移）。
        """
        base = Path(data_dir) / "sessions"
        if not base.is_dir():
            return 0
        target = base / default_workspace.id
        target.mkdir(parents=True, exist_ok=True)
        moved = 0
        for p in sorted(base.iterdir()):
            if p.is_dir() or p.suffix not in (".json", ".lock"):
                continue
            dest = target / p.name
            if dest.exists():
                continue  # 幂等：目标已有则跳过
            try:
                shutil.move(str(p), str(dest))
                moved += 1
            except OSError as exc:
                logger.warning("会话迁移失败（fail-open）: %s → %s: %s", p, dest, exc)
        if moved:
            logger.info("工作区迁移: %d 个旧会话移入 %s", moved, target)
        return moved
