"""held-out 评测集污染防线（运行时接入，P0）.

eval/rules/holdout.md §4 机制的运行时实现：把模型文本持久化的写点在落盘前
必须对**最终序列化载荷**过本模块（写侧 fail-closed，blocked 即拒写）；检索
读侧 fail-open（unavailable 放行但计数可见，见
introspection.search.RecordSearcher._filter_heldout_rows）。

写侧覆盖面（与实现逐点对齐；修改写路径时同步更新本清单）：
- method：卡片全文（save_candidate 首写经 ``MethodStore._commit_new_directory``、
  update_status / annotate_freshness / annotate_aliases 等 RMW 经
  ``MethodStore._replace_card``——检查对象是即将落盘的完整序列化卡片，不按
  字段拼装）+ usage 账本整行（record_use 的 note/suggestion 等）+
  qualification 账本整行（record_qualification 的 note/evidence_refs 等）；
- experience/lesson：``ExperienceStore.save`` 最终 payload（含 near-dup
  supersedes 追加后的复检）、status RMW 最终 payload、usage 账本整行；
- memory：条目 content/summary/keywords + citations/version_history（P2-7，
  Rule28 修复轮：后两者 model 可控，原排除口径可经 citations 绕探针，现以
  确定性 JSON 序列化并入同一 check_text 载荷；``MemoryStore.save_entry`` /
  ``save_entry_if_observed`` 共用 ``_reject_heldout_contamination``）；
- memory_extract：审计记录整行（``MemoryExtractor._audit``；fail-open 通道，
  blocked 时跳过该条审计写并告警）。
**不在检测面**（有意排除，勿凭本 docstring 反推覆盖）：episode 转录
（``data/episodes`` append-only 会话原文——逐字审计轨迹是可信源，拒写/改写
会破坏保真性，其污染控制依赖评测任务不进入生产会话的流程约束）；archive/
synopsis 等派生摘要（当前未接线，见各自模块）。

匹配口径（设计已定，勿改为 n-gram 覆盖率或哈希相等）：
- 每个 task 的探针 = task_id 原样 + 题面正文（去首行标题、空白规范化）按
  **24 字窗口、步长 4** 切出的重叠探针（正文 <24 字则整段一个探针），
  每 task 上限 16 个窗口、超出按等距抽样（保留首尾），丢弃空探针；
- 几何保证（为何是 24/4）：任一长度 ≥32 字的连续引用 [s, s+32) 完整包含
  某 24 字窗口 ⇔ 窗口起点 w ∈ [s, s+8]——9 个连续整数必含 4 的倍数，
  故步长 4 网格下 32 字片段 recall=1.0（48 字 3 窗口方案对 <48 字引用
  recall=0，已废弃）。等距抽样后相邻起点间距 ≤8 字（本 manifest 正文
  69–104 字 → 12–21 个窗口），保证在本集上仍成立；
- 检测面边界：**只为 statement.md 造探针**；solution.md 不造探针——
  解法代码/命令片段的短串重合率极高，纳入会大量误报。本 guard 的检测面
  = statement 探针 + task_id，解法泄漏依赖评测侧（sha256 锁定的题面/
  题解文件不出现在改进语料目录）而非本模块；
- 待检文本同样空白规范化后截断到前 200_000 字符；
- 探针子串命中即 blocked（单命中即判，无累计阈值）。

manifest 发现顺序：
1. env ``LFL_HELDOUT_MANIFEST``（文件存在才用；不存在则继续向下搜索，
   不因配置笔误而静默关闭防线）；
2. 从 cwd 向上逐级找 ``evals/heldout/v1/manifest.json``；
3. 包路径推导的仓库根（``Path(__file__).resolve().parents[3]``），且要求该根下
   确实存在 ``evals/heldout/v1`` 目录，否则视为未找到。
全部失败 → unavailable（fail-open）。

硬约束：**绝不把探针文本或待检文本写进日志/异常消息/返回值**——对外只出现
task_id 与类别（``task_id`` / ``statement_probe``）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger("llm_loop.knowledge.heldout_guard")

_PROBE_LEN = 24
_PROBE_STEP = 4
_MAX_PROBES_PER_TASK = 16
_TEXT_CAP = 200_000

# manifest 解析缓存与探针缓存共用同一 key=(path, mtime_ns, size)：
# statement 文件的 sha256 被 manifest 锁定，题面变更必然伴随 manifest 变更
# （mtime/size 变化 → key 变化 → 缓存失效）。
_MANIFEST_CACHE: dict[tuple[str, int, int], dict[str, Any]] = {}
_PROBE_CACHE: dict[tuple[str, int, int], dict[str, list[str]]] = {}
_CACHE_LOCK = threading.Lock()
_WARNED: set[str] = set()


class HeldoutContaminationError(Exception):
    """待写入内容命中 held-out 探针（写侧 fail-closed 拒写）。"""


def _warn_once(category: str, msg: str, *args: Any) -> None:
    """同类告警每进程最多一次（读侧逐行检查会放大日志量）。"""
    if category in _WARNED:
        return
    _WARNED.add(category)
    _LOGGER.warning(msg, *args)


def _normalize(text: str) -> str:
    """空白规范化：任意空白序列折叠为单空格（与旧 filter.py 口径一致）。"""
    return " ".join(str(text or "").split())


def find_manifest() -> Path | None:
    """按 env → cwd 向上 → 包推导仓库根 的顺序发现 held-out manifest。"""
    env_raw = str(os.environ.get("LFL_HELDOUT_MANIFEST", "") or "").strip()
    if env_raw:
        env_path = Path(env_raw).expanduser()
        if env_path.is_file():
            return env_path
    cwd = Path.cwd().resolve()
    for base in (cwd, *cwd.parents):
        cand = base / "evals" / "heldout" / "v1" / "manifest.json"
        if cand.is_file():
            return cand
    repo_root = Path(__file__).resolve().parents[3]
    if (repo_root / "evals" / "heldout" / "v1").is_dir():
        pkg_cand = repo_root / "evals" / "heldout" / "v1" / "manifest.json"
        if pkg_cand.is_file():
            return pkg_cand
    return None


def _cache_key(path: Path) -> tuple[str, int, int]:
    st = path.stat()
    return (str(path), st.st_mtime_ns, st.st_size)


def _load(path: Path, *, use_cache: bool = True) -> dict[str, Any]:
    """解析 manifest；缓存 key=(path, mtime_ns, size)，threading.Lock 保护。

    IO / JSON 解析 / 形状校验失败原样抛出，由 check_text 统一映射为 unavailable。
    """
    key = _cache_key(path)
    if use_cache:
        with _CACHE_LOCK:
            cached = _MANIFEST_CACHE.get(key)
        if cached is not None:
            return cached
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise ValueError("manifest shape invalid: tasks must be a list")
    if use_cache:
        with _CACHE_LOCK:
            _MANIFEST_CACHE[key] = data
    return data


def _window_probes(body: str) -> list[str]:
    """24 字窗口、步长 4 的重叠探针（正文 <24 字时整段作一个探针）。

    几何保证见模块 docstring：任一 ≥32 字连续引用必完整包含某个网格窗口
    （其窗口起点区间 [s, s+8] 含 9 个连续整数，必覆盖 4 的倍数）。窗口数
    超过 ``_MAX_PROBES_PER_TASK`` 时等距抽样降到上限（保留首尾；本集
    抽样后相邻起点间距 ≤8 字，保证仍成立）。
    """
    if len(body) <= _PROBE_LEN:
        return [body] if body else []
    last = len(body) - _PROBE_LEN
    starts = list(range(0, last + 1, _PROBE_STEP))
    if starts[-1] != last:
        starts.append(last)
    if len(starts) > _MAX_PROBES_PER_TASK:
        picked = sorted(
            {
                round(i * (len(starts) - 1) / (_MAX_PROBES_PER_TASK - 1))
                for i in range(_MAX_PROBES_PER_TASK)
            }
        )
        starts = [starts[i] for i in picked]
    return [body[s : s + _PROBE_LEN] for s in starts]


def _probes(manifest: dict[str, Any], root: Path) -> dict[str, list[str]]:
    """task_id → 探针列表（task_id 原样 + 正文 24 字/步长 4 重叠窗口；丢弃空探针）.

    纯函数：statement.md 不可读时该 task 退化为仅 task_id 探针（fail-open）。
    无换行的单行 statement 视为整段正文（与旧 filter 口径一致）。
    只读 statement.md；solution.md 有意不造探针（见模块 docstring 检测面边界）。"""
    out: dict[str, list[str]] = {}
    for task in manifest.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        tid = str(task.get("task_id") or "").strip()
        if not tid:
            continue
        candidates: list[str] = [tid]
        try:
            raw = (root / "tasks" / tid / "statement.md").read_text(encoding="utf-8")
        except OSError:
            raw = ""
        if raw:
            parts = raw.split("\n", 1)
            body = _normalize(parts[1] if len(parts) == 2 else parts[0])
            if body:
                candidates.extend(_window_probes(body))
        out[tid] = [p for p in dict.fromkeys(candidates) if p]
    return out


def _load_probes(
    path: Path, manifest: dict[str, Any], *, use_cache: bool = True
) -> dict[str, list[str]]:
    """探针缓存（与 manifest 缓存同 key；见模块头部说明）。"""
    key = _cache_key(path)
    if use_cache:
        with _CACHE_LOCK:
            cached = _PROBE_CACHE.get(key)
        if cached is not None:
            return cached
    probes = _probes(manifest, path.parent)
    if use_cache:
        with _CACHE_LOCK:
            _PROBE_CACHE[key] = probes
    return probes


def reset_cache() -> None:
    """清空 manifest/探针缓存与去重告警标记（测试用）。"""
    with _CACHE_LOCK:
        _MANIFEST_CACHE.clear()
        _PROBE_CACHE.clear()
    _WARNED.clear()


def _match(norm: str, probes: dict[str, list[str]]) -> dict[str, str] | None:
    for tid, plist in probes.items():
        for probe in plist:
            if probe in norm:
                return {
                    "status": "blocked",
                    "reason": "task_id" if probe == tid else "statement_probe",
                    "task_id": tid,
                }
    return None


def check_text(
    text: str | None,
    *,
    manifest_path: str | os.PathLike[str] | None = None,
    use_cache: bool = True,
) -> dict[str, str]:
    """检查文本是否命中 held-out 探针。

    返回 ``{"status": "clean"|"blocked"|"unavailable", "reason": str, "task_id": str}``：
    - 空/None → clean；
    - manifest 缺失 / 坏 JSON / 内部异常 → unavailable（fail-open）+ reason；
    - 命中任一探针 → blocked（reason 只写 ``task_id`` 或 ``statement_probe``）。

    硬约束：日志与返回值绝不包含探针文本或待检文本。
    """
    if not text:
        return {"status": "clean", "reason": "empty text", "task_id": ""}
    try:
        if manifest_path is not None:
            path: Path | None = Path(manifest_path).expanduser()
        else:
            path = find_manifest()
        if path is None:
            _warn_once(
                "manifest_not_found",
                "heldout manifest not found (env/cwd/package search); guard unavailable, fail-open",
            )
            return {"status": "unavailable", "reason": "manifest_not_found", "task_id": ""}
        manifest = _load(path, use_cache=use_cache)
        probes = _load_probes(path, manifest, use_cache=use_cache)
        hit = _match(_normalize(text)[:_TEXT_CAP], probes)
        if hit is not None:
            return hit
        return {"status": "clean", "reason": "no probe hit", "task_id": ""}
    except (OSError, ValueError) as exc:
        _warn_once(
            f"manifest_unreadable:{type(exc).__name__}",
            "heldout manifest unreadable (class=%s); guard unavailable, fail-open",
            type(exc).__name__,
        )
        return {
            "status": "unavailable",
            "reason": f"manifest_unreadable:{type(exc).__name__}",
            "task_id": "",
        }
    except Exception as exc:  # noqa: BLE001 — 内部异常 fail-open，且不得携带文本
        _warn_once(
            f"internal:{type(exc).__name__}",
            "heldout guard internal failure (class=%s); fail-open",
            type(exc).__name__,
        )
        return {
            "status": "unavailable",
            "reason": f"internal:{type(exc).__name__}",
            "task_id": "",
        }


def assert_not_heldout(
    text: str | None,
    manifest: dict[str, Any] | str | os.PathLike[str] | None = None,
) -> None | str:
    """旧签名兼容：None=通过；str=违规原因（只含类别与 task_id，不含正文）。

    ``manifest`` 兼容三种入参：已解析 dict（题面 root 用可发现的 manifest 所在
    目录，找不到时退化为仅 task_id 探针）/ manifest 路径 / None（自动发现）。
    unavailable 一律视为通过（fail-open，与旧 filter 语义一致）。
    """
    if not text:
        return None
    if isinstance(manifest, dict):
        found = find_manifest()
        root = found.parent if found is not None else Path.cwd()
        hit = _match(_normalize(text)[:_TEXT_CAP], _probes(manifest, root))
        if hit is not None:
            return f"held-out 泄漏({hit['reason']}): {hit['task_id']}"
        return None
    verdict = check_text(text, manifest_path=manifest)
    if verdict.get("status") == "blocked":
        return f"held-out 泄漏({verdict.get('reason')}): {verdict.get('task_id')}"
    return None
