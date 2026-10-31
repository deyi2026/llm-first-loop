"""compile_scope_roots 判定表采样测试（≥20 条，双向断言；T05 采样补充）.

与 tests/test_sandbox_scope_roots.py（判定表逐类单点用例）互补：本文件按采样
清单做批量采样——每条 pattern 预先写死**预期分类**，断言编译产物与之一致，
并对每条做双向断言：
- equivalent → (a) ScopeRoot.root 落在 workspace_root 之下、且 normpath 后等于
  字面前缀拼接结果；(c) 其子树内 3 个样本路径 scope_allows 全放行、且都落在
  对应 subpath 之下（glob 命中集 ⊇ 子树样本，不外溢到 subpath 之外）；
- amplifying → (b) 不允许静默当 equivalent：detail 必须写明放大原因；另断言
  一条「LFL 拒绝但落在候选 subpath 子树内」的见证路径——若把 subpath 交给内核
  将放行该路径（内核允许集 ⊋ glob 命中集，放大方向）；
- unverifiable → (b) subpath/root 恒为 None（不产生可用内核根，fail-closed）；
- deny 模式（判定表 5）→ 整体 not_supported、roots 恒空，绝不编译成内核 allow。

诚实清单（重要）:
- 本文件**不做任何真实 sandbox-exec 验证**：本环境 execute_command 自身运行在
  seatbelt 内，嵌套调用必然 sandbox_apply: Operation not permitted（退出码 71）。
  所有「内核允许/拒绝」断言都只针对**编译产物**（classification/subpath/root/
  detail）与 LFL 判定（scope_allows）的静态一致性，不声称测过内核行为。
- 含 `.`/`..`/空段的 pattern 已按「段级拒绝」修复（安全缺陷返修）：修前
  `../docs/**` 被标 equivalent 且 root 经 normpath **逃逸 workspace_root**、
  `docs/../src/**` 被标 equivalent 但 glob 命中集恒为空（rel 判定产物永不含
  `..` 段）。修后一律 unverifiable 且不产出 root；原 xfail(strict=True) 钉住的
  两个不变量用例已转正为正常断言（见 test_dotdot_* 各用例）。
- 空路径 pattern（""）在 parse_write_scope 层即被拒（paths 元素必须是非空
  str），不进入分类判定——采样清单「空路径（若允许）」的结论是**不允许**。
"""

from __future__ import annotations

import os

import pytest

from llm_loop.core.write_scope import (
    SCOPE_ROOT_AMPLIFYING,
    SCOPE_ROOT_EQUIVALENT,
    SCOPE_ROOT_UNVERIFIABLE,
    SCOPE_ROOTS_NOT_SUPPORTED,
    SCOPE_ROOTS_OK,
    compile_scope_roots,
    parse_write_scope,
    scope_allows,
)

WS = "/tmp/ws-sampling"  # 判定用 workspace_root：realpath 不要求目录真实存在


def _base() -> str:
    """与实现同口径的 root 基准：realpath(expanduser(workspace_root))."""
    return os.path.realpath(os.path.expanduser(WS))


def _under_base(path: str) -> bool:
    """path 是否落在 workspace_root 之下（与 scope_allows 边界同形态）."""
    return path == _base() or path.startswith(_base().rstrip("/") + "/")


# ── 采样表 ───────────────────────────────────────────────────────────────────
# equivalent：（原始 pattern, 归一后 pattern, 预期 subpath, 子树内 3 个样本 rel）
EQUIVALENT_SAMPLES = [
    ("docs/**", "docs/**", "docs", ("docs", "docs/a.md", "docs/x/y.md")),
    (
        "src/llm_loop/**",
        "src/llm_loop/**",
        "src/llm_loop",
        ("src/llm_loop", "src/llm_loop/core/write_scope.py", "src/llm_loop/a/b/c.py"),
    ),
    ("a/b/c/**", "a/b/c/**", "a/b/c", ("a/b/c", "a/b/c/f.txt", "a/b/c/d/e.bin")),
    (
        "中文目录/**",
        "中文目录/**",
        "中文目录",
        ("中文目录", "中文目录/文件 甲.md", "中文目录/子/乙.txt"),
    ),
    (
        "带 空格/**",
        "带 空格/**",
        "带 空格",
        ("带 空格", "带 空格/a b.md", "带 空格/x y/z.txt"),
    ),
    # 绝对路径形态：前导 `/` 被归一剥离，按相对 workspace_root 解释（≠ 系统 /tmp）
    ("/tmp/**", "tmp/**", "tmp", ("tmp", "tmp/a", "tmp/b/c")),
    # `~` 在 pattern 层不做 expanduser（归一只作用于被判定路径），按字面目录名编译
    ("~/**", "~/**", "~", ("~", "~/a.md", "~/b/c.txt")),
]

# amplifying：（原始 pattern, 归一后 pattern, 预期 subpath, LFL 拒绝但落在候选
# subpath 子树内的见证 rel——证明消费 subpath 会放大）
AMPLIFYING_SAMPLES = [
    ("docs", "docs", "docs", "docs/a.md"),
    ("src", "src", "src", "src/x.py"),
    ("a/b", "a/b", "a/b", "a/b/f"),
    ("docs/**/x", "docs/**/x", "docs", "docs/other/z.md"),
    ("a/*/c", "a/*/c", "a", "a/bb/d"),
    ("docs/*.md", "docs/*.md", "docs", "docs/sub/x.md"),
    ("docs/**/*.md", "docs/**/*.md", "docs", "docs/a/b.txt"),
    # 绝对字面路径：同上前导 `/` 剥离 → 裸目录名形态（判定表 2）
    ("/etc", "etc", "etc", "etc/hosts"),
    ("文档 目录", "文档 目录", "文档 目录", "文档 目录/f.md"),
]

# unverifiable：通配开头（**/y、*abc、**）或字面前缀为空（根指称归一形态 . / ./）
UNVERIFIABLE_SAMPLES = [
    ("**/y", "**/y"),
    ("*abc", "*abc"),
    ("**", "**"),
    (".", ""),
    ("./", ""),
]

# deny 模式（判定表 5）：整体 not_supported、roots 恒空（排除集无法用内核
# allow-subpath 表达，绝不编译成内核 allow）
DENY_SAMPLES = [
    {"paths": ["src/**"], "mode": "deny"},
    {"paths": ["docs"], "mode": "deny"},
    {"paths": ["**/y"], "mode": "deny"},
]


# ── 判定表 1：equivalent 采样（(a) root 锚定 + (c) 子树一致性）──────────────


@pytest.mark.parametrize(
    "raw,norm,sub,samples",
    EQUIVALENT_SAMPLES,
    ids=[p for p, _, _, _ in EQUIVALENT_SAMPLES],
)
def test_equivalent_sampling_root_anchored_and_lfl_hits_subtree(raw, norm, sub, samples):
    """equivalent → root=normpath(base+字面前缀) 且在 workspace 内；子树 3 样本 LFL 全放行."""
    scope = parse_write_scope({"paths": [raw]})
    assert scope is not None
    result = compile_scope_roots(scope, WS)
    assert result.status == SCOPE_ROOTS_OK
    (root,) = result.roots
    assert root.pattern == norm
    assert root.classification == SCOPE_ROOT_EQUIVALENT
    assert root.subpath == sub
    # (a) 与实现同口径的字面前缀拼接结果，且落在 workspace_root 之下
    assert root.root == os.path.normpath(os.path.join(_base(), sub))
    assert _under_base(root.root)
    # (c) 子树内 3 个样本：都落在 subpath 之下，scope_allows 全放行（glob 不外溢）
    for rel in samples:
        assert rel == sub or rel.startswith(sub + "/"), rel
        allowed, reason = scope_allows(scope, os.path.join(WS, rel), WS)
        assert allowed, f"{raw!r} 应放行子树样本 {rel!r}（scope_allows 返回 {reason!r}）"


# ── 判定表 2/3：amplifying 采样（(b) 显式放大原因 + 放大方向见证）───────────


@pytest.mark.parametrize(
    "raw,norm,sub,witness",
    AMPLIFYING_SAMPLES,
    ids=[p for p, _, _, _ in AMPLIFYING_SAMPLES],
)
def test_amplifying_sampling_reasoned_and_overgrant_witness(raw, norm, sub, witness):
    """amplifying → detail 写明放大原因（不静默当 equivalent）；见证路径证明 subpath 会放大."""
    scope = parse_write_scope({"paths": [raw]})
    assert scope is not None
    result = compile_scope_roots(scope, WS)
    assert result.status == SCOPE_ROOTS_OK
    (root,) = result.roots
    assert root.pattern == norm
    assert root.classification == SCOPE_ROOT_AMPLIFYING
    assert root.subpath == sub
    assert root.root == os.path.normpath(os.path.join(_base(), sub))
    assert "放大" in root.detail  # (b) 第一析取支：detail 明确标注放大原因
    # 放大方向见证（静态推导，非真实内核验证）：witness 被 LFL 拒绝，却落在候选
    # subpath 子树内 → 若按 equivalent 消费 subpath，该路径将被内核放行
    allowed, reason = scope_allows(scope, os.path.join(WS, witness), WS)
    assert allowed is False, f"{raw!r} 的见证路径 {witness!r} 应被 LFL 拒绝"
    assert reason == "not_in_allow_list"
    witness_abs = os.path.normpath(os.path.join(_base(), witness))
    sub_abs = os.path.normpath(os.path.join(_base(), sub))
    assert witness_abs.startswith(sub_abs.rstrip("/") + "/")


# ── 判定表 4：unverifiable 采样（(b) 不产生可用内核根）──────────────────────


@pytest.mark.parametrize(
    "raw,norm", UNVERIFIABLE_SAMPLES, ids=[p for p, _ in UNVERIFIABLE_SAMPLES]
)
def test_unverifiable_sampling_no_kernel_root(raw, norm):
    """unverifiable → subpath/root 恒 None（fail-closed，不产生可用等效内核根）."""
    scope = parse_write_scope({"paths": [raw]})
    assert scope is not None
    result = compile_scope_roots(scope, WS)
    assert result.status == SCOPE_ROOTS_OK  # 三分类是逐条的，整体状态仍 ok
    (root,) = result.roots
    assert root.pattern == norm
    assert root.classification == SCOPE_ROOT_UNVERIFIABLE
    assert root.subpath is None
    assert root.root is None
    assert "fail-closed" in root.detail


# ── 判定表 5：deny 模式采样（整体 not_supported）────────────────────────────


@pytest.mark.parametrize(
    "raw", DENY_SAMPLES, ids=[d["paths"][0] + ":deny" for d in DENY_SAMPLES]
)
def test_deny_mode_sampling_not_supported_roots_empty(raw):
    """deny 模式 → 整体 not_supported、roots 恒空，绝不编译成内核 allow."""
    scope = parse_write_scope(raw)
    assert scope is not None
    result = compile_scope_roots(scope, WS)
    assert result.status == SCOPE_ROOTS_NOT_SUPPORTED
    assert result.roots == ()
    assert "deny" in result.detail


# ── 采样覆盖下限自检 + 边缘形态专项 ─────────────────────────────────────────


def test_sampling_coverage_minimums():
    """采样下限自检：分类采样总数 ≥20，判定表 5 类每类 ≥3 条."""
    total = (
        len(EQUIVALENT_SAMPLES)
        + len(AMPLIFYING_SAMPLES)
        + len(UNVERIFIABLE_SAMPLES)
        + len(DENY_SAMPLES)
    )
    assert total >= 20
    for name, samples in (
        ("equivalent", EQUIVALENT_SAMPLES),
        ("amplifying", AMPLIFYING_SAMPLES),
        ("unverifiable", UNVERIFIABLE_SAMPLES),
        ("deny→not_supported", DENY_SAMPLES),
    ):
        assert len(samples) >= 3, name


def test_empty_path_pattern_rejected_at_parse():
    """采样清单「空路径（若允许）」：不允许——解析层即拒（paths 元素必须非空 str）."""
    assert parse_write_scope({"paths": [""]}) is None


def test_bare_trailing_wildcard_xstar_unverifiable_undergrant_direction():
    """`X*`（首段尾部通配、无 `/`，如 docs*）→ 当前归 unverifiable（判定表 4）.

    方向注意（与 amplifying 相反，任务书易错点）：LFL 侧 ``docs*`` 命中 ``docsx``
    等根下单段，但编译产物 subpath/root 均为 None——若消费方只信内核根，这类命中
    将**漏授权**（内核比 LFL 严，fail-closed 安全侧方向）。当前分类 =
    unverifiable（非 amplifying），此处如实断言；裁决建议见任务回报。
    """
    scope = parse_write_scope({"paths": ["docs*"]})
    assert scope is not None
    (root,) = compile_scope_roots(scope, WS).roots
    assert root.classification == SCOPE_ROOT_UNVERIFIABLE
    assert root.subpath is None and root.root is None
    # LFL 命中（docsx）但无内核根可编译 → 漏授权方向的直接证据；`*` 不跨 `/`
    allowed, _ = scope_allows(scope, os.path.join(WS, "docsx"), WS)
    assert allowed is True
    allowed_deep, _ = scope_allows(scope, os.path.join(WS, "docsx/a.py"), WS)
    assert allowed_deep is False


# ── 含 `.`/`..`/空段 pattern：段级拒绝（双保险第一道，修复后行为）────────────


def test_dotdot_inside_workspace_unverifiable_current_behavior():
    """`docs/../src/**` → unverifiable、无 root：原「equivalent 但命中集恒空」失真已修.

    修前（父级实测钉住）：`..` 被当字面段走判定表 1 → equivalent、root 锚到
    base/src 整棵子树；而 rel 判定产物永不含 `..` 段，glob 命中集恒为空——LFL 对
    src 全拒，按 equivalent 消费即放大。修后段级拒绝 fail-closed；LFL 侧拒绝
    行为保持不变（不放宽）。
    """
    scope = parse_write_scope({"paths": ["docs/../src/**"]})
    assert scope is not None
    (root,) = compile_scope_roots(scope, WS).roots
    assert root.classification == SCOPE_ROOT_UNVERIFIABLE
    assert root.subpath is None and root.root is None
    assert "fail-closed" in root.detail
    allowed, reason = scope_allows(scope, os.path.join(WS, "src/a.py"), WS)
    assert allowed is False and reason == "not_in_allow_list"  # 命中集恒空证据


def test_dotdot_inside_workspace_equivalent_consistency_invariant():
    """原 xfail(strict=True) 用例转正：一致性不变量修复后成立.

    钉住的不变量：不存在「标 equivalent 而其声称子树被 LFL 全拒」的失真条目。
    修复方式是把 `..` 段 pattern 整体挡在 equivalent 之外（unverifiable），失真
    源头移除——不变量从「被违反（xfail）」变为「结构性成立（正常断言）」。
    """
    scope = parse_write_scope({"paths": ["docs/../src/**"]})
    (root,) = compile_scope_roots(scope, WS).roots
    assert root.classification != SCOPE_ROOT_EQUIVALENT
    assert root.classification == SCOPE_ROOT_UNVERIFIABLE
    assert root.subpath is None and root.root is None
    allowed, reason = scope_allows(scope, os.path.join(WS, "src/a.py"), WS)
    assert allowed is False and reason == "not_in_allow_list"


def test_dotdot_escape_workspace_unverifiable_current_behavior():
    """`../docs/**` → unverifiable 且 root=None：root 逃逸 workspace_root 已修.

    修前（父级实测钉住）：equivalent 且 root=normpath(base/../docs)（逃逸到工作
    区外）。若 on 阶段消费该编译结果，等于把工作区外子树交给内核——放大回退，
    安全缺陷。修后不产出任何 root；LFL 层 outside_scope 语义不变（本就不放行）。
    """
    scope = parse_write_scope({"paths": ["../docs/**"]})
    assert scope is not None
    (root,) = compile_scope_roots(scope, WS).roots
    assert root.classification == SCOPE_ROOT_UNVERIFIABLE
    assert root.subpath is None and root.root is None
    assert "fail-closed" in root.detail
    escaped = os.path.normpath(os.path.join(_base(), "..", "docs", "x.md"))
    assert not _under_base(escaped)  # 前提自检：修前的逃逸目标确实在 base 外
    allowed, reason = scope_allows(scope, escaped, WS)
    assert allowed is False and reason == "outside_scope"  # LFL 语义不变


def test_dotdot_escape_workspace_root_must_stay_inside():
    """原 xfail(strict=True) 用例转正：不变量 (a)——root 必在 workspace 之内.

    修复后 `../X/**` 不再产出 root（unverifiable），「逃逸的 equivalent 根」无从
    产生；该不变量由 root 围栏（双保险第二道）结构性保证：任何分支产出的 root
    一旦越出 base 即降级 unverifiable 且 root=None。
    """
    scope = parse_write_scope({"paths": ["../docs/**"]})
    (root,) = compile_scope_roots(scope, WS).roots
    assert root.classification == SCOPE_ROOT_UNVERIFIABLE
    assert root.subpath is None and root.root is None  # 不产出 root ⇒ 无越界 root


# ── 段级拒绝判定表（含正向对照）+ root 围栏全局不变量（修复回归钉）───────────

# 段级拒绝采样：归一后仍含 `.`/`..`/空段的形态（前导 `./` 已在归一层剥除，不在此列）
SEGMENT_REJECT_SAMPLES = [
    "../docs/**",  # .. 首段：修前 root 逃逸 workspace_root（安全缺陷本体）
    "docs/../src/**",  # .. 中段：修前 equivalent 失真（glob 命中集恒空）
    "../../etc/**",  # 多级 .. 上翻：逃逸形态加压
    "docs//src/**",  # 空段：归一不消除中段 //，与 _deny_entry_viable 同口径拒绝
    "docs/./src/**",  # 中段 `.`：归一只剥前导 ./，中段 . 残留 → 同口径拒绝
]


@pytest.mark.parametrize(
    "pattern",
    SEGMENT_REJECT_SAMPLES,
    ids=["leading-dotdot", "mid-dotdot", "double-dotdot", "empty-seg", "mid-dot"],
)
def test_segment_level_rejection_all_unverifiable_no_root(pattern):
    """段级拒绝（双保险第一道）：含 `.`/`..`/空段 → unverifiable 且 root=None."""
    scope = parse_write_scope({"paths": [pattern]})
    assert scope is not None  # allow 模式 parse 不做段检查（贡献为空=fail-closed 侧）
    result = compile_scope_roots(scope, WS)
    assert result.status == SCOPE_ROOTS_OK  # 逐条三分类，整体状态仍 ok
    (root,) = result.roots
    assert root.classification == SCOPE_ROOT_UNVERIFIABLE
    assert root.subpath is None
    assert root.root is None
    assert "fail-closed" in root.detail


def test_leading_dot_prefix_equivalent_not_overrejected():
    """正向对照（防误伤）：前导 `./` 经归一剥除 → equivalent、root 在 base 内.

    语义决策：段级拒绝作用于**归一后** pattern（与 parse 层 deny 段检查同一作用
    点，`_deny_entry_viable` 亦作用于归一产物）——`./docs/**` 归一为 `docs/**`，
    无 `.` 段残留，且 LFL glob 侧同样剥前导 `./`（语义一致），仍判 equivalent。
    仅拒绝归一后仍有 `.`/`..`/空段的形态，正向路径未被误伤。
    """
    scope = parse_write_scope({"paths": ["./docs/**"]})
    assert scope is not None
    (root,) = compile_scope_roots(scope, WS).roots
    assert root.pattern == "docs/**"  # 归一形态
    assert root.classification == SCOPE_ROOT_EQUIVALENT
    assert root.subpath == "docs"
    assert root.root == os.path.normpath(os.path.join(_base(), "docs"))
    assert _under_base(root.root)


def test_all_sampled_roots_stay_inside_base_invariant():
    """root 围栏不变量（双保险第二道，全局遍历）：对全部采样逐条断言——

    - classification=equivalent 的产物必有 root 且 root 落在 base 内（修复的
      核心不变量，任何 equivalent 都不得逃逸 workspace_root）；
    - amplifying 同受围栏约束（必有 root 且在 base 内）；
    - unverifiable 必无 root/subpath（fail-closed，不产出可用内核根）。
    """
    raws = (
        [p for p, _, _, _ in EQUIVALENT_SAMPLES]
        + [p for p, _, _, _ in AMPLIFYING_SAMPLES]
        + [p for p, _ in UNVERIFIABLE_SAMPLES]
        + list(SEGMENT_REJECT_SAMPLES)
    )
    for raw in raws:
        scope = parse_write_scope({"paths": [raw]})
        assert scope is not None, raw
        result = compile_scope_roots(scope, WS)
        assert result.status == SCOPE_ROOTS_OK, raw
        (root,) = result.roots
        if root.classification == SCOPE_ROOT_UNVERIFIABLE:
            assert root.root is None and root.subpath is None, raw
        else:  # equivalent / amplifying：必有 root 且被围栏限定在 base 内
            assert root.root is not None, raw
            assert _under_base(root.root), (raw, root.root)
        if root.classification == SCOPE_ROOT_EQUIVALENT:
            assert root.root is not None and _under_base(root.root), raw

