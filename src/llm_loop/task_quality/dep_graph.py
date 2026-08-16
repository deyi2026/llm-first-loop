"""路径 K：依赖图（design.md §2.1 / spec §5.6）.

项目模块间 import 关系的静态分析，用于反向查找受影响测试子集。

- 首次构建: ast.parse 解析项目源文件 import 关系构建有向图
  （DepNode MODULE/TEST + DepEdge imports/imported_by）
- 构建超时 build_timeout_s（缺省 60s）→ ([], False) fail-open
- 内存缓存（进程级），可选落盘 cache_path（fail-open，损坏重建）
- affected_tests(): modified_files → imported_by → 测试节点（反向查找）
- 增量更新: 仅分析变更文件（increment_timeout_s 缺省 5s）→ 超时重建
- 只读源文件（不修改任何项目文件）
- 线程安全（threading.Lock 保护图结构）
"""

from __future__ import annotations

import ast
import json
import logging
import threading
import time
from pathlib import Path

from llm_loop.task_quality.models import DepNode, DepNodeType

logger = logging.getLogger(__name__)


class DepGraph:
    """import 依赖图（静态分析 + 反向查找受影响测试）."""

    def __init__(
        self,
        *,
        src_root: Path,
        test_root: Path | None = None,
        cache_path: Path | None = None,
        build_timeout_s: float = 60.0,
        increment_timeout_s: float = 5.0,
    ) -> None:
        self._src_root = Path(src_root)
        self._test_root = Path(test_root) if test_root else Path(src_root)
        self._cache_path = Path(cache_path) if cache_path else None
        self._build_timeout_s = build_timeout_s
        self._increment_timeout_s = increment_timeout_s
        self._lock = threading.Lock()
        self._nodes: dict[str, DepNode] = {}
        self._edges: dict[str, set[str]] = {}  # node_id -> imported node_ids
        self._imported_by: dict[str, set[str]] = {}  # node_id -> importers
        self._built = False

    # ── 构建 ──
    def build(self) -> bool:
        """首次构建依赖图（ast 解析 import 关系）.

        Returns:
            True=构建成功；False=失败/超时（fail-open 回退全量）。
        """
        start = time.perf_counter()
        try:
            nodes: dict[str, DepNode] = {}
            edges: dict[str, set[str]] = {}
            imported_by: dict[str, set[str]] = {}
            py_files = [p for p in self._src_root.rglob("*.py")
                        if ".git" not in p.parts and "__pycache__" not in p.parts]
            for fp in py_files:
                if time.perf_counter() - start > self._build_timeout_s:
                    logger.warning("依赖图构建超时（fail-open）: %s", self._build_timeout_s)
                    return False
                node = self._make_node(fp)
                nodes[node.node_id] = node
                for imp in self._parse_imports(fp):
                    edges.setdefault(node.node_id, set()).add(imp)
                    imported_by.setdefault(imp, set()).add(node.node_id)
            with self._lock:
                self._nodes, self._edges, self._imported_by = nodes, edges, imported_by
                self._built = True
            self._persist_cache()
            return True
        except Exception as exc:  # noqa: BLE001 — 构建失败 fail-open
            logger.warning("依赖图构建失败（fail-open）: %s", exc)
            return False

    def _make_node(self, fp: Path) -> DepNode:
        """文件 → 节点（tests/ 目录或 test_ 前缀为 TEST，否则 MODULE）.

        node_id 用去 src 前缀的相对路径（对齐 import 名，如 llm_loop.x.y），
        使 `from llm_loop.task_quality import models` 能反向匹配。
        """
        rel = fp.relative_to(self._src_root)
        is_test = (
            "tests" in fp.parts
            or fp.name.startswith("test_")
            or fp.name.endswith("_test.py")
        )
        ntype = DepNodeType.TEST if is_test else DepNodeType.MODULE
        # 去掉 src/ 前缀（若存在）→ node_id 与 import 名对齐
        parts = list(rel.parts)
        if parts and parts[0] == "src":
            parts = parts[1:]
        node_id = ".".join(parts)[:-3]
        return DepNode(node_type=ntype, node_id=node_id, file_path=str(fp))

    @staticmethod
    def _parse_imports(fp: Path) -> list[str]:
        """ast 解析文件 import 的模块名（含相对导入解析）."""
        try:
            tree = ast.parse(fp.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            return []
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                # from X import Y → 记录 X 和 X.Y（Y 可能是模块或符号，宽匹配）
                imports.append(node.module.split(".")[0])
                for alias in node.names:
                    if alias.name and not alias.name.startswith("_"):
                        imports.append(f"{node.module}.{alias.name.split('.')[0]}")
        return imports

    # ── 反向查找 ──
    def affected_tests(self, modified_files: list[str]) -> tuple[list[str], bool]:
        """反向查找受影响测试子集.

        Args:
            modified_files: 修改文件路径列表。

        Returns:
            (受影响测试文件路径列表, 依赖图可用性)。
            依赖图不可用 → ([], False)（调用方回退全量）。
        """
        with self._lock:
            if not self._built:
                return [], False
            affected: set[str] = set()
            for mf in modified_files:
                # 修改文件 → 模块 id（对齐 node_id 生成：去 src 前缀）
                try:
                    mf_rel = Path(mf).resolve().relative_to(self._src_root.resolve())
                except ValueError:
                    continue
                parts = list(mf_rel.parts)
                if parts and parts[0] == "src":
                    parts = parts[1:]
                mod_id = ".".join(parts)[:-3]
                # imported_by 传递: 直接/间接导入者中找 TEST 节点
                queue = list(self._imported_by.get(mod_id, set()))
                seen: set[str] = set()
                while queue:
                    importer = queue.pop(0)
                    if importer in seen:
                        continue
                    seen.add(importer)
                    node = self._nodes.get(importer)
                    if node is not None and node.node_type == DepNodeType.TEST:
                        affected.add(node.file_path)
                    queue.extend(self._imported_by.get(importer, set()))
            return sorted(affected), True

    # ── 增量更新 ──
    def incremental_update(self, changed_files: list[str]) -> bool:
        """增量更新（仅分析变更文件；超时重建）.

        Returns:
            True=更新成功；False=失败（需重建）。
        """
        start = time.perf_counter()
        try:
            with self._lock:
                if not self._built:
                    return self.build()
                for cf in changed_files:
                    if time.perf_counter() - start > self._increment_timeout_s:
                        logger.warning("依赖图增量更新超时 → 重建")
                        return self.rebuild()
                    fp = Path(cf)
                    if not fp.exists():
                        continue
                    node = self._make_node(fp)
                    self._nodes[node.node_id] = node
                    # 清除旧边
                    for imp in list(self._edges.get(node.node_id, set())):
                        self._imported_by.get(imp, set()).discard(node.node_id)
                    self._edges[node.node_id] = set()
                    for imp in self._parse_imports(fp):
                        self._edges.setdefault(node.node_id, set()).add(imp)
                        self._imported_by.setdefault(imp, set()).add(node.node_id)
                self._persist_cache()
                return True
        except Exception as exc:  # noqa: BLE001 — 增量失败需重建
            logger.warning("依赖图增量更新失败（重建）: %s", exc)
            return self.rebuild()

    def rebuild(self) -> bool:
        """重建依赖图（增量失败/缓存损坏时）."""
        self._built = False
        ok = self.build()
        return ok

    # ── 缓存 ──
    def _persist_cache(self) -> None:
        """可选落盘缓存（fail-open：失败/损坏重建）."""
        if self._cache_path is None:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "nodes": [{"id": n.node_id, "type": n.node_type.value, "file": n.file_path}
                          for n in self._nodes.values()],
                "edges": {src: sorted(dst) for src, dst in self._edges.items()},
            }
            self._cache_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:
            logger.warning("依赖图缓存落盘失败（fail-open）: %s", exc)

    def load_cache(self) -> bool:
        """从缓存恢复（损坏/失败 → False 触发重建）."""
        if self._cache_path is None or not self._cache_path.exists():
            return False
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            with self._lock:
                self._nodes = {
                    n["id"]: DepNode(
                        DepNodeType(n["type"]), n["id"], n["file"]
                    ) for n in data.get("nodes", [])
                }
                self._edges = {k: set(v) for k, v in data.get("edges", {}).items()}
                self._imported_by = {}
                for src, dsts in self._edges.items():
                    for dst in dsts:
                        self._imported_by.setdefault(dst, set()).add(src)
                self._built = True
            return True
        except (OSError, ValueError, KeyError) as exc:
            logger.warning("依赖图缓存加载失败（重建）: %s", exc)
            return False

    # ── 查询 ──
    def node_count(self) -> int:
        with self._lock:
            return len(self._nodes)

    def edge_count(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._edges.values())

    def is_built(self) -> bool:
        with self._lock:
            return self._built


# 协议别名（tasks.md §6.1）
DepGraphProtocol = DepGraph
