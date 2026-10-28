"""Facts about the wheel installation, independent of the task workspace."""

from __future__ import annotations

import json
import re
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
    """单一真值根下的规则文档候选路径（模式确定后不跨根试探）。

    wheel 安装（bundle_root 命中）只看 ``llm_loop/_bundled/docs/``；源码检出
    只看仓库根 ``docs/``。sys.prefix、site-packages、CWD、DATA_DIR、用户 home
    永不作为回退候选——回退根上的同名文件只会掩盖 bundle 损坏（Linux 0.6.37
    wheel 旁路事故的收敛项）。
    """
    bundled = bundle_root()
    if bundled is not None:
        return (bundled / "docs" / name,)
    module = Path(__file__).resolve()
    return (module.parents[3] / "docs" / name,)   # 源码检出：<repo>/src/llm_loop/runtime/installation.py


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
