"""Facts about the wheel installation, independent of the task workspace."""

from __future__ import annotations

import json
import re
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path


def bundle_root() -> Path | None:
    root = Path(__file__).resolve().parents[1] / "_bundled"
    return root if (root / "manifest.json").is_file() else None


def installed_identity(module: Path) -> dict[str, str] | None:
    """Recognize a distribution-owned package, never a relocated source checkout."""
    root = bundle_root()
    if root is None:
        return None
    try:
        dist = distribution("llm-first-loop")
        owned_module = Path(str(dist.locate_file("llm_loop/__init__.py"))).resolve()
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        listed = {str(f) for f in dist.files or ()}
        if (
            module.resolve() != owned_module
            or "llm_loop/_bundled/manifest.json" not in listed
            or manifest.get("schema") != "lfl.application-bundle/v1"
            or manifest.get("version") != dist.version
        ):
            return None
        return {"name": "llm-first-loop", "version": dist.version,
                "package_root": str(owned_module.parent)}
    except (PackageNotFoundError, OSError, ValueError, AttributeError):
        return None


def rules_doc_candidates(name: str) -> tuple[Path, ...]:
    """Candidate locations of a packaged rule document, most specific first.

    两种安装布局都必须能解析到同一个规则文件：wheel 安装把规则文档随包放在
    ``llm_loop/_bundled/docs/``；源码检出把它们留在仓库根 ``docs/``。
    任务工作区只存运行期数据，不是规则真值源，因此永不作为候选。
    """
    roots: list[Path] = []
    bundled = bundle_root()
    if bundled is not None:
        roots.append(bundled)
    module = Path(__file__).resolve()
    roots.append(module.parents[3])   # 源码检出：<repo>/src/llm_loop/runtime/installation.py
    roots.append(Path(sys.prefix))     # wheel 安装：<venv>/docs
    roots.append(module.parents[2])   # site-packages（docs 与包同级）
    seen: set[Path] = set()
    candidates: list[Path] = []
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        candidates.append(root / "docs" / name)
    return tuple(candidates)


def rules_version() -> str:
    """读 docs/ai_rules.lite.md 头部 version=N；失败/缺失返回空串.

    与规则索引同源解析（bundle_root 优先，源码检出回退仓库根），
    使 wheel 安装与源码检出在同一版本文件上得到一致结论。
    """
    for path in rules_doc_candidates("ai_rules.lite.md"):
        try:
            head = path.read_text(encoding="utf-8")[:512]
        except OSError:
            continue
        match = re.search(r"version\s*=\s*(\d+)", head)
        if match:
            return match.group(1)
    return ""
