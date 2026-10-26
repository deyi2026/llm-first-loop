"""held-out 读侧封条：评测/改进期禁止读侧工具触达 held-out 任务材料。

判定口径（逐条对应 eval/rules/holdout.md §3：改进期读取 held-out 题面/solution 即该轮作废）:
- 开关：env ``LFL_HELDOUT_SEALED`` ∈ {"1","true","yes"}（大小写不敏感）。为假时**任何**
  判定立即放行 —— 开发态零行为变化，这是本模块的硬要求。
- 归一：``os.path.expanduser`` → 相对路径先按 ``run_context.workspace_base()`` 拼接 →
  ``os.path.realpath``。不用 ``Path.resolve()``：不存在的文件不抛错，且 realpath 已展开
  symlink 与 ``..``。
- 命中两条并存：
  a) 归一路径等于或位于任一 sealed root 之下（按路径分隔符边界判定，
     故 ``.../tasks_evil`` 不会误命中 ``.../tasks``）；
  b) 归一路径含字面片段 ``/evals/heldout/v1/tasks``（防 sealed root 因目录缺失而失效；
     同样按边界判定，故 ``.../tasks_backup`` 放行）。
- macOS 大小写不敏感文件系统：比较前 ``casefold()``（``os.path.normcase`` 在 darwin 上
  不折叠大小写，故不用）。
- 相对路径基准：``run_context.workspace_base()``；import 失败退化为 ``Path.cwd()``
  （import 放函数内，避免循环导入）。
- 内部异常：fail-open 放行 + ``warning`` 一次；拒绝原因只含类别与 root 说明，
  **绝不回显文件内容**。

接线点（读侧 guard / 写侧防复制篡改）:
- ``tools/builtin/read_file.py``：``p`` 解析完（含 workspace_base 拼接、symlink 标注之前）
  且在任何磁盘 IO / path_registry 登记之前。
- ``tools/builtin/search_files.py``：``root``/``path`` 参数命中即拒；glob 与 content 两种
  模式的**结果列表**逐条过滤（不补位，回执写明过滤条数）。
- ``tools/builtin/inspect_code.py``：入口 guard。
- ``tools/builtin/source_synopsis.py``：``source_ref`` 为文件路径（非 ``artifact://`` /
  ``evidence://`` 等 scheme）时 guard。
- ``tools/builtin/edit_file.py``：写侧 guard（防把封条内材料复制/篡改到别处）。
- ``tools/builtin/execute_command.py``（P2-8，Rule28 修复轮）：``execute()`` 入口对
  命令串做**字面片段拒绝**（``sealed_command_reason``，归一 = lower + 连续空白
  折叠，命中 ``evals/heldout/v1/tasks`` / ``evals/heldout`` / ``/heldout/v1/``
  任一即拒）。这是 deny-by-default 的第一道门，配合事后 verify_isolation.py。

明确不覆盖（已知残余，靠其它层或显式声明兜底）:
- ``execute_command`` 的**非字面**形态：变量拼接（``P=evals/held; cat $P/out/v1``）、
  间接构造、base64 等编码可绕过字面片段拒绝——已知边界（不做 shell 语义解析，
  解析即引入误放行/误拒绝两类风险），由事后 verify_isolation.py 审计兜底。
- 浏览器 ``file://`` 读取。
- ``read_evidence`` 等对**已捕获** evidence 的重放（捕获发生在封条启用之前时无法回收）。
- 封条自身不审计「谁尝试读了什么」——只做拦截，不做取证。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_SEAL_ENV = "LFL_HELDOUT_SEALED"
_ROOT_ENV = "LFL_HELDOUT_ROOT"
_TRUE_VALUES = frozenset({"1", "true", "yes"})
# 第二命中口径：字面片段（防 sealed root 因目录缺失而失效）
_LITERAL_MARKERS: tuple[str, ...] = ("/evals/heldout/v1/tasks",)
# darwin 默认大小写不敏感文件系统，字符串比较前需 casefold（normcase 不解决该问题）
_CASE_INSENSITIVE = sys.platform == "darwin"


def seal_enabled() -> bool:
    """封条是否启用（真值集 {"1","true","yes"}，大小写不敏感）。"""
    raw = os.environ.get(_SEAL_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in _TRUE_VALUES


def _repo_root() -> Path:
    # src/llm_loop/sealed_paths.py → parents[2] = 仓库根
    return Path(__file__).resolve().parents[2]


def sealed_roots() -> list[Path]:
    """sealed root 清单：env LFL_HELDOUT_ROOT（目录存在才用）否则仓库 held-out tasks 根。"""
    raw = os.environ.get(_ROOT_ENV) or ""
    raw = raw.strip()
    if raw:
        try:
            candidate = Path(raw).expanduser()
            if candidate.is_dir():
                return [candidate]
        except OSError:  # pragma: no cover - 极端权限/坏路径，回落到默认根
            pass
    return [_repo_root() / "evals" / "heldout" / "v1" / "tasks"]


def reset_cache() -> None:
    """测试用：清空内部缓存。

    当前实现不缓存任何判定结果（每次调用实时读 env，避免测试改 env 后拿到旧结论），
    本函数保留为稳定 API：调用前后行为等价。
    """


def _base_dir() -> Path:
    """相对路径基准：工作区根；import 失败退化为进程 cwd（避免循环导入）。"""
    try:
        from llm_loop.core.run_context import workspace_base

        return Path(workspace_base())
    except Exception:  # noqa: BLE001 - fail-open 到 cwd，绝不因基准缺失而误判
        return Path.cwd()


def _norm(path: str | os.PathLike[str]) -> str:
    """expanduser → 相对路径拼工作区根 → realpath（不要求文件存在）。"""
    raw = os.path.expanduser(str(path))
    if not os.path.isabs(raw):
        raw = os.path.join(str(_base_dir()), raw)
    return os.path.realpath(raw)


def _cmp(value: str) -> str:
    """比较用归一：darwin 大小写不敏感文件系统上折叠大小写。"""
    return value.casefold() if _CASE_INSENSITIVE else value


def _under_root(target: str) -> str | None:
    """target 等于或位于任一 sealed root 之下 → 返回 root 展示串，否则 None。"""
    t = _cmp(target)
    for root in sealed_roots():
        try:
            r = _cmp(_norm(root))
        except OSError:  # pragma: no cover - 根路径不可 realpath 时跳过该根
            continue
        if not r:
            continue
        if t == r or t.startswith(r.rstrip(os.sep) + os.sep):
            return str(root)
    return None


def _literal_marker(target: str) -> str | None:
    """target 命中字面片段（按路径边界，防 tasks_backup 误命中）→ 返回 marker。"""
    t = _cmp(target)
    for marker in _LITERAL_MARKERS:
        norm_marker = _cmp(os.sep.join(marker.split("/")))
        idx = t.find(norm_marker)
        if idx < 0:
            continue
        tail = t[idx + len(norm_marker):]
        if tail == "" or tail.startswith(os.sep):
            return marker
    return None


# execute_command 命令串字面片段（P2-8，Rule28 修复轮）：归一（lower + 连续空白
# 折叠）后子串命中即拒。三个口径分别为完整 tasks 根、短形根、v1 子树内任意位置。
_COMMAND_MARKERS: tuple[str, ...] = (
    "evals/heldout/v1/tasks",
    "evals/heldout",
    "/heldout/v1/",
)


def sealed_command_reason(command: str) -> str | None:
    """判定 execute_command 命令串是否携带 held-out 材料的字面路径片段（P2-8）.

    返回 None = 放行；返回 str = 拒绝原因（只含类别，绝不回显命令内容/路径）。

    - 封条未启用（``seal_enabled()`` 为假）→ 恒 None，开发态零行为变化（硬要求）。
    - 归一口径：lower + 连续空白折叠为单空格（``cat  EVALS/HELDOUT/v1/tasks`` 与
      ``cat evals/heldout/v1/tasks`` 等价；路径段内部的空白变形不做语义推断）。
    - 已知边界（docstring 记录，不算缺陷）：变量拼接（``P=evals/held; cat $P/out/v1``）、
      间接构造、编码变形可绕过——本函数是 deny-by-default 的第一道门（字面片段
      拒绝），非 shell 语义解析；事后由 verify_isolation.py 审计兜底。
    """
    if not seal_enabled():
        return None
    normalized = " ".join(str(command or "").lower().split())
    if not normalized:
        return None
    for marker in _COMMAND_MARKERS:
        if marker in normalized:
            return (
                "held-out 封条：命令串含 held-out 任务材料的字面路径片段"
                "（类别：literal_path）；评测/改进期禁止读取 held-out 题面、"
                "solution 或测试材料（该轮结果会作废）"
            )
    return None


def sealed_path_reason(path: str | os.PathLike[str]) -> str | None:
    """判定路径是否落在 held-out 封条内。

    返回 None = 放行；返回 str = 拒绝原因（只含类别与 root 说明，绝不回显文件内容）。
    """
    if not seal_enabled():
        return None
    try:
        target = _norm(path)
        if not target:
            return None
        hit = _under_root(target) or _literal_marker(target)
        if hit is None:
            return None
        return (
            f"held-out 封条：该路径位于 held-out 任务材料根 {hit} 之下；"
            "评测/改进期禁止读取 held-out 题面、solution 或测试材料（该轮结果会作废）"
        )
    except Exception as exc:  # noqa: BLE001 - 判定异常一律 fail-open 并留一条 warning
        logger.warning("[held-out 封条] 判定异常，已放行（fail-open）: %r", exc)
        return None
