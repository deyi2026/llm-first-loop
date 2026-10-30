"""写侧授权核心契约层（P0，DESIGN-20261030 §5.1/§5.2/§5.4/§5.8）.

本模块只做**声明解析 + 路径判定 + 父子求交 + 进程内审计**四件纯算法/契约事，
不做强制点（edit_file/execute_command 的接线在 C6-C8）、不做传递链注入
（runner 的 C5）、不做受保护路径默认清单（§5.8 P2）。

契约要点（对接方按此调用）:
- ``parse_write_scope``: 解析 ``requires.write_scope`` 原始值；返回 None 一律表示
  「非法结构」，调用方据此回参数错误（与 ``requires.tools`` 处理一致）。
  三分态必须在解析层区分（§5.2，FR-3/FR-4）:
  a) ``{"paths": [...]}`` / ``{"paths": [], "mode": "allow"}`` → ``declared=True``
     （后者 = 显式只读，FR-4）；``{"paths": [], "mode": "deny"}`` → None
     （空排除集 = 全量放行陷阱，非法结构，见 parse_write_scope 文档字符串）;
  b) dict 内**不含** ``paths`` 键（如 ``{}``）→ ``declared=False``（= 键不存在/
     未声明，继承父，FR-3）。``declared=False`` 的对象在本模块所有入口
     （``scope_allows`` / ``intersect_write_scope``）一律按「未声明」归一处理。
- ``scope_allows``: 归一口径与 ``llm_loop.sealed_paths._norm`` 一致——
  ``expanduser`` → 相对路径拼 ``workspace_root`` → ``os.path.realpath``（不要求
  文件存在；**禁止** ``Path.resolve()``，不存在文件会抛错）→ darwin 上
  ``casefold()``。glob 按路径分隔符边界判定（``src*`` 不命中 ``srcevil/x.py``），
  不用 fnmatch 裸比（``.*`` 会跨 ``/``）。
- ``intersect_write_scope``: 交集实现为**路径谓词的合取**（parent 允许 AND child
  允许），不是 pattern 字符串集合运算。越界（子声明不被父覆盖）→ 拒绝并返回
  refusal_detail，**不静默截断**（FR-2）。

已知边界（诚实清单，不宣称已覆盖）:
- 审计存储是**模块级 + threading.Lock**：仅同进程内跨线程可见，子代理若是独立
  进程（或本进程重启），审计即丢失——P0 已知边界，跨进程持久化留待后续。
- glob 覆盖判据（父覆盖子）是**保守近似**（fail-closed）：仅认 ``q == p``、
  ``q`` 以 ``/**`` 结尾且 ``p`` 落在该目录前缀下、``q`` 是 ``p`` 的目录前缀三种；
  ``q="src/*"`` 不覆盖 ``p="src/a"``（glob-in-glob 不可证明 → 拒绝）。
- pattern 里的字符类（``[a-z]``）按字面翻译，不支持跨段类；``src//x`` 这类
  中间空段（及 ``.``/``..`` 段）永不匹配：allow 模式下=空转 allow 条目
  （fail-closed 拒写）；deny 模式下=空转排除项（fail-open 全量放行陷阱），
  解析层确定性拒绝（第二轮返修 A，``_deny_entry_viable``）。
- 判定异常（极端路径/权限）一律 fail-closed 拒绝（写侧不能 fail-open），
  返回 ``outside_scope``。
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

MAX_PATTERNS = 64
MAX_PATTERN_LEN = 512

MODE_ALLOW = "allow"
MODE_DENY = "deny"
_VALID_MODES = frozenset({MODE_ALLOW, MODE_DENY})

# darwin 默认大小写不敏感文件系统，比较前 casefold（与 sealed_paths 同口径；
# os.path.normcase 在 darwin 上不折叠大小写，故不用）
_CASE_INSENSITIVE = sys.platform == "darwin"


@dataclass(frozen=True)
class WriteScope:
    """一个执行域的写侧声明（glob pattern 相对 workspace_root）.

    - ``paths``: mode=allow 时是允许集（空 = 显式只读，拒绝一切写，FR-4）；
      mode=deny 时是排除集（deny 优先于 allow）。空排除集 = 全量放行，
      与只读外观方向相反——``parse_write_scope`` 确定性拒绝该组合（P2-1），
      含「归一后为空 / 含空段、``.``/``..`` 段」的空转排除项（第二轮返修 A）。
    - ``mode``: "allow" | "deny"。
    - ``declared``: False 表示「键不存在 = 继承父」（未声明），True 表示显式声明
      （含 ``paths: []`` 显式只读）。``declared=False`` 的对象在本模块所有判定
      入口按「未声明」归一（等价 None），paths 必须为空。
    - ``deny_paths``: 求交过程中叠加的 deny 集（父链累积），优先于 paths 判定。
    """

    paths: tuple[str, ...]
    mode: str = MODE_ALLOW
    declared: bool = True
    deny_paths: tuple[str, ...] = ()


# ── 归一（口径 = sealed_paths._norm，基准改由参数显式传入，避免依赖 run_context）──


def _cmp(value: str) -> str:
    """比较用归一：darwin 大小写不敏感文件系统上折叠大小写."""
    return value.casefold() if _CASE_INSENSITIVE else value


def _norm(path: str, workspace_root: str) -> str:
    """expanduser → 相对路径拼 workspace_root → realpath（不要求文件存在）."""
    raw = os.path.expanduser(str(path))
    if not os.path.isabs(raw):
        raw = os.path.join(str(workspace_root), raw)
    return os.path.realpath(raw)


# ── glob 编译（按路径分隔符边界；不用 fnmatch 裸比）──


def _translate_segment(seg: str) -> str:
    """单段 glob → 正则。``*``/``?`` 不跨 ``/``；``[...]`` 字符类保留区间语义."""
    out: list[str] = []
    i, n = 0, len(seg)
    while i < n:
        c = seg[i]
        if c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and seg[j] in "!^":
                j += 1
            if j < n and seg[j] == "]":  # 首个 ] 是字面成员（[]] 语义）
                j += 1
            while j < n and seg[j] != "]":
                j += 1
            if j >= n:  # 未闭合 → 字面 [
                out.append(re.escape("["))
                i += 1
                continue
            inner = seg[i + 1 : j]
            negate = bool(inner) and inner[0] in "!^"
            if negate:
                inner = inner[1:]
            body = "".join("\\" + ch if ch in "\\]" else ch for ch in inner)
            out.append("[" + ("^" if negate else "") + body + "]")
            i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


@lru_cache(maxsize=512)
def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """整条 pattern（相对路径 glob）→ 锚定正则。``**`` 段 = 任意层目录.

    - ``src/**`` 命中 ``src/a/b.py``（也命中 ``src`` 本身，目录级写允许）;
    - ``src*`` 只命中根下单段（``srcfoo``），不命中 ``srcevil/x.py``;
    - ``**/x`` 命中 ``x`` 与 ``a/b/x``; ``a/**/b`` 命中 ``a/b`` 与 ``a/c/b``。
    """
    norm = pattern
    while norm.startswith("./"):
        norm = norm[2:]
    norm = norm.lstrip("/")
    parts = ["**" if seg == "**" else _translate_segment(seg) for seg in norm.split("/")]
    out = ""
    sep = False  # out 尾部是否已含段分隔符（** 组的每次重复自带尾 /）
    last = len(parts) - 1
    for idx, part in enumerate(parts):
        if part == "**":
            if idx == last:
                out = (out + "(?:/[^/]+)*") if out else "[^/]+(?:/[^/]+)*"
            else:
                # 两种形态的组自身携带分隔语义（重复项各自带尾 /），下一段不再补 /
                out = (out + "(?:/[^/]+)*/") if out else "(?:[^/]+/)*"
                sep = True
        elif out == "":
            out = part
            sep = False
        elif sep:
            out += part
            sep = False
        else:
            out += "/" + part
            sep = False
    return re.compile(out + r"\Z")


def _matches(pattern: str, rel: str) -> bool:
    return _pattern_regex(_cmp(pattern)).match(_cmp(rel)) is not None


# ── pattern 归一（P2-6：统一存储/比较形态，不动匹配语义）──


def _normalize_pattern(pattern: str) -> str:
    """pattern 形态归一：去前导 ``./``、去前导 ``/``、去尾部 ``/``、裸 ``.`` → ``''``.

    目的：让 ``"./src/**"`` 与 ``"src/**"`` 落到同一存储形态，使
    ``_covered_by`` 的覆盖判定（字符串比较）与 allow/deny 判定都基于归一
    后形式，不再出现「子 ``./src/a`` 被父 ``src/**`` 误判越界」的形态性误拒。
    - 只动形态不动匹配语义：``_pattern_regex`` 编译时本就剥离前导 ``./`` 与
      ``/``，此处把同一口径提前到解析层并额外剥离尾部 ``/``（``docs/`` ≡
      ``docs``）；
    - 反斜杠按字面保留（POSIX 下是合法文件名字符，改写会变更匹配语义）；
    - **根指称形态归一为空串**（第二轮返修 A，fail-open 边缘）：``"."``、
      ``"./"``、``"/"``、``"//"``、``"/."``、``"././"`` … 都指 workspace 根
      本身，统一归一为 ``''``。P2-6 时曾采用「归一后为空保留原串，交由 glob
      永不匹配（fail-closed）」——该口径在 allow 模式确实 fail-closed（空
      允许集=只读），但在 deny 模式是 **fail-open**：永不匹配的排除项=
      空转排除集=全量放行陷阱（P2-1 同性质）。故改为归一到 ``''``，由
      ``parse_write_scope`` 按 mode 分流（deny 非法 / allow=只读贡献）。
    - 幂等：已归一输入原样返回（``''`` → ``''``，``"src"`` → ``"src"``）。
    """
    p = pattern
    while True:
        if p.startswith("./"):
            p = p[2:]
        elif p.startswith("/"):
            p = p[1:]
        elif len(p) > 1 and p.endswith("/"):
            p = p[:-1]
        else:
            break
    # 裸 "."（含 "/."、"./." 剥壳后的残余）是根指称，与 ""/"/" 同形态
    return "" if p == "." else p


def _deny_entry_viable(pattern: str) -> bool:
    """deny 排除项「句法可匹配性」检查（fail-closed，非完备性证明）.

    deny 模式下 paths 是排除集：**永不匹配的排除项 = 空转排除**，若它是
    唯一条目即等价空排除集 = 全量放行（P2-1 同性质 fail-open 陷阱，第二轮
    返修 A 实测枚举）。本检查只拦截三类确定性「永不匹配」形态：
    a) 归一后为空（根指称形态 ``""``/``"."``/``"./"``/``"/"``/``"//"`` …）；
    b) ``"/"`` 分割后含空段（``"a//b"``——relpath 产物不含空段）；
    c) 段为 ``"."``/``".."``（``"src/./x"``、``"../x"``——realpath 归一后的
       rel 不含这两类段）。
    这只是句法检查：不重构 glob 引擎、不试图证明任意 pattern 的可满足性；
    其余 glob 边界（字符类等）仍按既有 fail-closed 口径处理。allow 模式
    不做此检查——永不匹配的 allow 条目 = 贡献为空 = fail-closed（方向安全）。
    """
    if not pattern:
        return False
    return all(seg and seg not in (".", "..") for seg in pattern.split("/"))


# ── 解析 ──


def parse_write_scope(raw: object) -> WriteScope | None:
    """解析 ``requires.write_scope`` 原始值。

    raw 合法结构: ``{"paths": [str, ...], "mode": "allow"|"deny"}``。
    返回 None 一律表示「非法结构」，调用方据此回参数错误。

    - raw 必须是 dict；不是 → None
    - ``paths`` 键存在时必须是 ``list[str]``；不是 → None
    - ``mode`` 存在时必须是 ``"allow"``/``"deny"``；否则 → None
    - paths 元素必须是非空 str；否则 → None
    - ``len(paths) > 64`` → None；任一元素 ``len > 512`` → None
    - ``paths == []`` 且 mode=allow → 只读语义（declared=True，paths 为空）
    - ``paths == []`` 且 mode=deny → None（非法结构，P2-1 返修）。语义统一
      定义：allow 模式下 paths=允许集（空 = 只读，FR-4）；deny 模式下
      paths=排除集（空 = 全量放行，与只读外观方向相反，是「看起来只读、
      实际全量」的 fail-open 陷阱）。要表达只读用 ``{"paths": []}``（allow），
      要表达全量用不声明 write_scope 或 ``{}``。
    - mode=deny 且任一排除项「永不匹配」（归一后为空的根指称形态
      ``"."``/``"./"``/``"/"``/``"//"``…，或含空段、``.``/``..`` 段）→ None
      （第二轮返修 A）。此类「空转排除项」从排除集里漏掉一切路径，单条
      即等价空排除集=全量放行（P2-1 同性质 fail-open；修前实测
      ``{"paths": ["./"], "mode": "deny"}`` 对任意路径 ``(True, "")``）。
      语义决策选定**选项 3**：deny 模式一律非法结构（fail-closed 拒绝声明，
      不猜意图）；allow 模式同形态保持合法——空转 allow 条目贡献为空，
      单条等价 ``paths=[]`` 只读，方向 fail-closed，与既有 FR-4 语义一致。
    - dict 内不含 ``paths`` 键 → ``declared=False``（键不存在 = 继承父），
      paths 为 ()，mode 取合法声明值或默认 allow
    - pattern 元素经 ``_normalize_pattern`` 归一后存储（``./src/**`` ≡ ``src/**``，
      尾部 ``/`` 剥离，根指称 ``"."``/``"./"``/``"/"`` → ``''``），消除同一
      pattern 的形态差异（P2-6 返修；根指称 → ``''`` 为第二轮返修 A）
    - 未知键忽略（向前兼容，不做 schema 全量校验）
    """
    if not isinstance(raw, dict):
        return None
    mode = MODE_ALLOW
    if "mode" in raw:
        mode_raw = raw["mode"]
        if not isinstance(mode_raw, str) or mode_raw not in _VALID_MODES:
            return None
        mode = mode_raw
    if "paths" not in raw:
        return WriteScope(paths=(), mode=mode, declared=False)
    paths_raw = raw["paths"]
    if not isinstance(paths_raw, list):
        return None
    if len(paths_raw) > MAX_PATTERNS:
        return None
    for item in paths_raw:
        if not isinstance(item, str) or not item:
            return None
        if len(item) > MAX_PATTERN_LEN:
            return None
    normalized = tuple(_normalize_pattern(item) for item in paths_raw)
    if mode == MODE_DENY:
        # P2-1：空排除集 + deny = 全量放行陷阱（与 FR-4 空 paths=只读方向相反），
        # 解析层确定性拒绝 → 调用方（SurfaceRequirements.from_kwargs /
        # spawn_subagent）走既有「非法结构 → 参数错误」链路
        if not normalized:
            return None
        # 第二轮返修 A（P2-1 同性质 fail-open，修前实测：{"paths": ["./"],
        # "mode": "deny"} 对任意路径 (True, "") 全量放行）：排除集含「永不
        # 匹配」的空转条目（归一后为空的根指称形态，或空段/"."/".." 段）
        # 同样非法。语义决策=选项 3：deny 模式一律 None——不采用「空 pattern
        # 在 deny 模式匹配一切」（选项 2：反直觉，且「归一后回退原串」才是
        # 根因），也不「静默丢弃空转条目」（会掩盖声明者对语义的误解）。
        # allow 模式不做此检查：永不匹配的 allow 条目=贡献为空=fail-closed。
        if any(not _deny_entry_viable(p) for p in normalized):
            return None
    return WriteScope(paths=normalized, mode=mode, declared=True)


# ── 判定 ──


def scope_allows(scope: WriteScope | None, abs_path: str, workspace_root: str) -> tuple[bool, str]:
    """判定单个绝对路径是否在 scope 内。返回 ``(allowed, reason)``。

    reason 取值仅限:
      ``""`` 允许；``"outside_scope"`` 不在 workspace_root 之下（含 ``..`` 穿越/
      绝对路径越界/symlink 逃逸）；``"not_in_allow_list"`` 在 root 下但不匹配
      allow pattern；``"denied_by_deny_list"`` 命中 deny（deny 优先于 allow）。

    - ``scope is None``（或 ``declared=False``）表示「全量」，恒返回 ``(True, "")``。
    - 判定顺序：归一 → root 边界 → deny（deny_paths + deny 模式的 paths）
      → allow 匹配。
    - 判定异常 fail-closed（写侧不能 fail-open）→ ``(False, "outside_scope")``。
    """
    if scope is None or not scope.declared:
        return (True, "")
    try:
        target = _norm(abs_path, workspace_root)
        root = os.path.realpath(os.path.expanduser(str(workspace_root)))
        t, r = _cmp(target), _cmp(root)
        if not (t == r or t.startswith(r.rstrip("/") + "/")):
            return (False, "outside_scope")
        rel = os.path.relpath(target, root)
    except Exception as exc:  # noqa: BLE001 - 写侧判定异常必须 fail-closed
        logger.warning("[write_scope] 判定异常，已拒绝（fail-closed）: %r", exc)
        return (False, "outside_scope")
    for pat in scope.deny_paths:
        if _matches(pat, rel):
            return (False, "denied_by_deny_list")
    if scope.mode == MODE_DENY:
        for pat in scope.paths:
            if _matches(pat, rel):
                return (False, "denied_by_deny_list")
        return (True, "")
    for pat in scope.paths:
        if _matches(pat, rel):
            return (True, "")
    return (False, "not_in_allow_list")


# ── 父子求交 ──


def _deny_set(scope: WriteScope) -> tuple[str, ...]:
    """scope 的完整 deny 集：显式 deny_paths + deny 模式下 paths 本身也是排除集."""
    if scope.mode == MODE_DENY:
        return scope.deny_paths + scope.paths
    return scope.deny_paths


def _covered_by(pattern: str, parent_paths: tuple[str, ...]) -> bool:
    """保守覆盖判据（fail-closed）：glob-in-glob 不可证明即不覆盖.

    比较前对两侧做 ``_normalize_pattern`` 归一（P2-6 返修）：``"./src/a"`` 与
    父 ``"src/**"`` 不再因前导 ``./`` 的形态差异被误判「超出父 scope」。
    归一幂等，对 parse 产物（已归一）零影响；对直接构造的 WriteScope 也成立。

    认三种：``q == p``；``q`` 以 ``/**`` 结尾且 ``p`` 等于该目录或落在其下
    （按分隔符边界收紧——任务书字面 ``p.startswith(q[:-3])`` 会把 ``srceviol``
    误认在 ``src`` 下，违反「交集=路径谓词合取」原则，故收紧为
    ``p == q[:-3] or p.startswith(q[:-3] + "/")``）；``q`` 是 ``p`` 的目录前缀
    （``p`` 以 ``q + "/"`` 开头）。
    """
    p = _normalize_pattern(pattern)
    for q_raw in parent_paths:
        q = _normalize_pattern(q_raw)
        if q == p:
            return True
        if q.endswith("/**"):
            base = q[:-3]
            if p == base or p.startswith(base + "/"):
                return True
        if p.startswith(q + "/"):
            return True
    return False


def intersect_write_scope(
    parent: WriteScope | None, child: WriteScope | None
) -> tuple[WriteScope | None, str]:
    """父子 scope 求交。返回 ``(effective, refusal_detail)``。

    - child 未声明（None 或 ``declared=False``）→ ``(parent, "")`` 继承。
    - parent 全量（None 或 ``declared=False``）→ ``(child, "")`` 子原样生效。
    - child.mode == "deny" → deny 只收紧不放宽。父为 allow 模式：父 allow 集
      不变，child.paths 叠加进 deny_paths（``WriteScope(paths=parent.paths,
      mode="allow", declared=True, deny_paths=parent.deny_paths + child.paths)``）。
      父也为 deny 模式：谓词合取 ¬P ∧ ¬C = ¬(P∪C)，结果仍用 deny 模式形态
      表达（``WriteScope(paths=P∪C, mode="deny")``，paths=排除集）——不降级成
      allow 模式 + 空 allow 集：allow 模式下 paths=() 表示只读（拒绝一切），
      会把 deny 集整个遮蔽成「一切被拒 + not_in_allow_list 误导原因」
      （P1-1 返修）；deny 模式形态对再次求交封闭（孙代继承语义不变）。
    - child.mode == "allow"：越界检查——parent 为 allow 模式时，child.paths 每条
      必须被 parent.paths 覆盖（``_covered_by`` 保守判据），否则
      ``(None, "write_scope 声明超出父 scope: <越界项列表>")``，不静默截断。
      通过则 effective 允许集 = child.paths（单路径判定上等价于交集），
      parent 的 deny 集原样继承。
    """
    if child is None or not child.declared:
        return (parent, "")
    if parent is None or not parent.declared:
        return (child, "")
    if child.mode == MODE_DENY:
        deny_union = _deny_set(parent) + child.paths
        if parent.mode == MODE_DENY:
            # P1-1：deny ∩ deny = 「除 P∪C 外全允许」，用既有 deny 模式形态
            # 表达（paths=排除集）。不降级成 allow 模式：allow 模式下空
            # allow 集表示只读（拒绝一切），会把 deny 集整个遮蔽，且拒绝
            # 原因会误导为 not_in_allow_list（真实原因是命中/不命中排除集）。
            return (WriteScope(paths=deny_union, mode=MODE_DENY, declared=True), "")
        # 父 allow 模式：deny 只收紧不放宽，父 allow 集原样保留
        return (
            WriteScope(
                paths=parent.paths,
                mode=MODE_ALLOW,
                declared=True,
                deny_paths=deny_union,
            ),
            "",
        )
    if parent.mode == MODE_ALLOW:
        uncovered = [p for p in child.paths if not _covered_by(p, parent.paths)]
        if uncovered:
            return (None, "write_scope 声明超出父 scope: " + ", ".join(uncovered))
    return (
        WriteScope(
            paths=child.paths,
            mode=MODE_ALLOW,
            declared=True,
            deny_paths=_deny_set(parent),
        ),
        "",
    )


# ── 进程内审计（模块级 + Lock：同进程跨线程可见；跨进程/重启即丢失，P0 已知边界）──

_audit_lock = threading.Lock()
_written_paths: list[str] = []
_violations: list[dict[str, str]] = []
_unverified_paths: list[dict[str, str]] = []
_audit_dropped = 0

# 进程内审计的条目上限：审计是**观测**用途，不是日志；无上限会让长会话的审计
# 列表无限增长（独立审查 P2-4）。超限条目计数丢弃，不静默。
_AUDIT_MAX_ENTRIES = 500


def _append_capped(bucket: list, item) -> None:
    """按上限追加审计条目；超限则计数丢弃（调用方须持锁）。"""
    global _audit_dropped
    if len(bucket) >= _AUDIT_MAX_ENTRIES:
        _audit_dropped += 1
        return
    bucket.append(item)


def write_scope_audit_record_write(path: str) -> None:
    """记录一次「scope 内合法写」的路径（供父会话观测实际写集合，FR-11）."""
    with _audit_lock:
        _append_capped(_written_paths, str(path))


def write_scope_audit_record_violation(path: str, reason: str) -> None:
    """记录一次越界写尝试（path + scope_allows 的 reason）."""
    with _audit_lock:
        _append_capped(_violations, {"path": str(path), "reason": str(reason)})


def write_scope_audit_record_unverified(path: str, reason: str) -> None:
    """记录一次「放行但无法证明落在 scope 内」的路径（scope_unverified 审计）.

    与 violation 的区别：violation 是**被拒**的越界写尝试；unverified 是**已放行**
    但闸无法静态证明在 scope 内（命令通道读侧越界字面量、cwd 位移后的显式相对
    路径）。两者都进审计，但语义相反——观测面必须能区分「被拒」与「未验证」。
    """
    with _audit_lock:
        _append_capped(_unverified_paths, {"path": str(path), "reason": str(reason)})


def write_scope_audit_snapshot() -> dict[str, Any]:
    """审计快照: ``{"written_paths": [...], "violations": [{"path","reason"}...],
    "violation_count": int, "scope_unverified": [{"path","reason"}...],
    "scope_unverified_count": int}``（返回拷贝，调用方可自由持有）."""
    with _audit_lock:
        return {
            "written_paths": list(_written_paths),
            "violations": [dict(v) for v in _violations],
            "violation_count": len(_violations),
            "scope_unverified": [dict(v) for v in _unverified_paths],
            "scope_unverified_count": len(_unverified_paths),
            "audit_dropped_count": _audit_dropped,
        }


def write_scope_audit_reset() -> None:
    """清空进程内审计（测试隔离 / runner 每_child 重置用；签名清单外的辅助 API）."""
    global _audit_dropped
    with _audit_lock:
        _written_paths.clear()
        _violations.clear()
        _unverified_paths.clear()
        _audit_dropped = 0
