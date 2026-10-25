"""T4(2026-08-14) 评测运行器：评测集 → 真实 LLM N 样本 → 判定 → Wilson CI → 报告落盘.

用法:
    # 真实 LLM（需 DEEPSEEK_API_KEY/LLM_API_KEY；样本数为场景定义值）
    .venv/bin/python scripts/run_eval.py

    # 指定样本数与输出目录
    .venv/bin/python scripts/run_eval.py --samples 3 --output docs/metrics/eval_20260814

    # dry 模式：内置 fixture 轨迹验证判定/统计/报告管道（零 LLM 零网络）
    .venv/bin/python scripts/run_eval.py --dry

    # held-out A 级口径（预算对齐）：产品预算 + 忽略场景 pin
    .venv/bin/python scripts/run_eval.py --budget-profile product --ignore-scenario-pins

输出:
    <output>/report.json  结构化对账（每场景 k/n + 率 + Wilson CI + 样本详情）
    <output>/report.md    markdown 渲染（CI 区间/基线引用/如实标注）

纪律（playbook 4.x）: 样本不足如实标注；不宣称统计显著（CI 重叠即不显著）；
负结果与正结果同等呈现；报告含评测集版本与场景口径引用。
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 代码源解析面（2026-10-27 修订，R1-R6）：
# - 2026-10-23 曾把 src 无条件前插 sys.path（防 PYTHONPATH 指向 .releases 快照）。
#   现收敛为 **--code-source=worktree** 的显式行为：auto（默认）= 继承环境，
#   但必打证据行 + 漂移告警（resolve_code_source），不再静默改解析面。
# - llm_loop 的 import 一律延迟到 resolve_code_source() 之后（函数内 import）：
#   模块级 import 发生在 argparse 之前，--code-source 的路径准备/断言将对
#   首个 import 失效（R2）。
# - 项目根本身仍在路径中（兼容 `data/` 等以根为基准的相对路径读取；根下无
#   llm_loop 包，不影响 llm_loop 解析）。
sys.path.insert(0, str(_PROJECT_ROOT))

# ── 跑批 scratch + 封条（2026-10-24）────────────────────────────────────
# scratch 根：**系统临时目录**，不落仓库。此前默认 <repo>/data/e2e → 每轮跑批把
# 题面/轨迹文本写进仓库，之后 search_files/grep 一扫即自我污染（实测残留
# 414 个 data/e2e/eval-run-*、373MB）。产物（report.json/report.md/checkpoint）
# 位置不变，只搬 scratch。
_SCRATCH_ROOT = Path(tempfile.gettempdir()) / "lfl-e2e"

# 封条开关 env 名：跑批期间置 "1"。只设这个字符串，**不 import
# llm_loop.sealed_paths**——封条模块由别处维护，评测脚本不与之硬耦合。
_SEAL_ENV = "LFL_HELDOUT_SEALED"


@contextlib.contextmanager
def _heldout_seal():
    """跑批期间置 LFL_HELDOUT_SEALED=1；退出（含异常）恢复原值，原本不存在则删除。"""
    prev = os.environ.get(_SEAL_ENV)
    os.environ[_SEAL_ENV] = "1"
    try:
        yield os.environ.get(_SEAL_ENV)
    finally:
        if prev is None:
            os.environ.pop(_SEAL_ENV, None)
        else:
            os.environ[_SEAL_ENV] = prev


def _sealed_batch(fn):
    """整个跑批（evaluate 全程）处于封条下；异常也复原（封条漏出进程更危险）。"""

    @functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        with _heldout_seal():
            return fn(*args, **kwargs)

    return _wrapped


# ── 知识库状态显式化（2026-10-25 修订）──────────────────────────────────
# 原 docs/HELDOUT-GUARD-20261025.md §6-1 的前提（eval 会读写生产知识库）不成立：
# factory 的 Settings-env 解析不读 os.environ（见下 2)），生产库本就不会被评测碰。
# 真实缺口是：eval 每样本的知识库是空目录，与生产（约 1408 method 卡 / 626
# experience 文件）不同质 → 跨知识库状态的 Δpass@1 不可归因。本块把知识库
# 状态显式化（不是"堵泄漏"）：
# - empty（默认）: 每样本空目录（零知识基线，明示而非隐性）；
# - snapshot: 生产 experiences/ 与 data/methods/ **深拷贝**到
#   <run_scratch>/knowledge-snapshot/ 后逐样本再复制（写入不回流生产）。
# production 模式已删除：无可堵的"泄漏"，保留只会让口径漂移。
#
# 「环境不可覆盖」的机制（R1）：
#   1) factory.build_engine 的权威解析是
#      `_runtime_paths = settings._extra.get("runtime_paths")`（factory.py:1641），
#      是 RuntimePaths 实例就直接采用，**不再调用 resolve_runtime_paths**
#      （factory.py:1642 的 isinstance 分支短路）→ 注入后 settings 字段与
#      os.environ 的 METHODS_DIR/EXPERIENCES_DIR 都不参与这条路径；
#   2) 注入的 RuntimePaths 本身由本脚本用 env={} 显式解析基底
#      （resolve_runtime_paths 只读传入 env：paths.py:130 `values = os.environ
#      if env is None else env`；env={} 时 EXPERIENCES_DIR/METHODS_DIR
#      读取（paths.py:155-156）拿到空串 → 走 data_dir 推断），
#      再 dataclasses.replace 显式改写目标目录。
#   注：.env:198-199 含 EXPERIENCES_DIR/METHODS_DIR=生产路径，load_env_file()
#   会把它们放进 os.environ——显式注入天然免疫这一陷阱。
#
# 为何用显式注入（settings._extra["runtime_paths"]）而非"环境变量过滤"：
# 过滤只对已枚举的读取点兜底，后来新增的 env 读取无法被穷举；显式注入走
# factory 的 authoritative isinstance 分支，把知识库位置钉死在 RuntimePaths
# 实例上——与 os.environ 的瞬时状态无关，也不依赖"记得过滤"。
_KNOWLEDGE_MODES = ("empty", "snapshot")


def _knowledge_sources() -> tuple[Path, Path]:
    """知识库源目录（snapshot 拷贝源）：仓库 experiences/ 与 data/methods/。"""
    root = Path(__file__).resolve().parent.parent
    return root / "experiences", root / "data" / "methods"


def _count_files(*dirs: Path) -> int:
    """递归统计目录下普通文件数（证据行 files=<n> 的口径）。"""
    n = 0
    for d in dirs:
        if d.is_dir():
            n += sum(1 for p in d.rglob("*") if p.is_file())
    return n


def prepare_knowledge_binding(
    run_scratch: Path,
    mode: str,
    sources: tuple[Path, Path] | None = None,
) -> dict:
    """准备 run 级知识库快照，返回绑定描述（stderr 证据行 + 逐样本复制源）。

    snapshot 用**显式深拷贝**（shutil.copytree），不用硬链接/cp -al：硬链接共享
    inode，副本侧就地写（jsonl append 等）会直接改到源文件（APFS 硬链接非
    copy-on-write），"写入不回流"无法成立——宁可付一次真实拷贝的成本。
    快照落 <run_scratch>/knowledge-snapshot/{experiences,methods}（run 级一份，
    逐样本再复制见 per_sample_knowledge）。
    ``sources`` 仅供测试注入小 fixture 源；缺省 = 仓库源目录（_knowledge_sources）。
    """
    if mode not in _KNOWLEDGE_MODES:
        raise ValueError(f"未知 knowledge-store 模式: {mode!r}（可选 {_KNOWLEDGE_MODES}）")
    src_exp, src_methods = sources if sources is not None else _knowledge_sources()
    exp_dst = run_scratch / "knowledge-snapshot" / "experiences"
    methods_dst = run_scratch / "knowledge-snapshot" / "methods"
    if mode == "snapshot":
        shutil.copytree(src_exp, exp_dst)
        shutil.copytree(src_methods, methods_dst)
    else:  # empty
        exp_dst.mkdir(parents=True, exist_ok=True)
        methods_dst.mkdir(parents=True, exist_ok=True)
    return {
        "mode": mode,
        "experiences": str(exp_dst),
        "methods": str(methods_dst),
        "files": _count_files(exp_dst, methods_dst),
    }


def bound_runtime_paths(binding: dict, data_dir):
    """由绑定目录构造 RuntimePaths（塞进 Settings._extra 供 factory 直接采用）。

    ``data_dir`` 必须显式传入并覆盖基底解析结果——它是**样本自己的**数据目录
    （session/memory/向量缓存挂其下），不覆盖则跨样本共享（P1 隐患）。
    基底 resolve_runtime_paths 传 env={}（不碰 os.environ），再显式 replace
    experiences/methods；code_root 保持仓库根——skills/docs/method 种子是
    **只读**真值源，随仓库走，不隔离。
    experiences_source/methods_source 用字面 "eval_binding"（消费方 knowledge/
    health.py 只比较 "data_dir_inferred"，不会误判为环境注入）。
    """
    from dataclasses import replace

    from llm_loop.runtime.paths import resolve_runtime_paths

    base = resolve_runtime_paths(
        data_dir=str(data_dir),
        code_root=_PROJECT_ROOT,
        env={},  # 显式空 env：父进程 METHODS_DIR/EXPERIENCES_DIR 在此不生效
    )
    return replace(
        base,
        data_dir=Path(data_dir),
        experiences_dir=Path(binding["experiences"]),
        methods_dir=Path(binding["methods"]),
        experiences_source="eval_binding",
        methods_source="eval_binding",
    )


def per_sample_knowledge(binding: dict, sample_dir: Path):
    """把 run 级知识库绑定落到单样本 tmp：<sample>/knowledge/{experiences,methods}。

    snapshot 模式再 copytree 一份到样本目录（run 级快照与源目录都不被动到，
    样本写入只落自己副本）；empty 模式建空目录。返回 RuntimePaths
    （data_dir=<sample>/data），由调用方塞进 settings._extra["runtime_paths"]。
    """
    sample_dir = Path(sample_dir)
    exp_dst = sample_dir / "knowledge" / "experiences"
    methods_dst = sample_dir / "knowledge" / "methods"
    if binding["mode"] == "snapshot":
        shutil.copytree(Path(binding["experiences"]), exp_dst)
        shutil.copytree(Path(binding["methods"]), methods_dst)
    else:  # empty
        exp_dst.mkdir(parents=True, exist_ok=True)
        methods_dst.mkdir(parents=True, exist_ok=True)
    return bound_runtime_paths(
        {"experiences": str(exp_dst), "methods": str(methods_dst)},
        data_dir=sample_dir / "data",
    )


# ── 代码源显式化（2026-10-27，R1-R6）────────────────────────────────────
# 缺陷背景（本轮对抗审核发现）：会话可能运行在 release 快照工作区
# （LFL_WORKSPACE_ROOT=.releases/<hash>），sitecustomize 把 <workspace_root>/src
# 前插 sys.path → 裸 python 与 run_eval 实际加载 .releases 旧代码，而 pytest
# 因 pyproject pythonpath 测工作树 —— "测的不是你以为的代码"。
# 本块把评测实际加载的 llm_loop 解析面显式化：
#   auto（默认）  继承环境 + 证据行 + 漂移告警（不拦）；
#   worktree      REPO/src 前插 sys.path[0] + 解析断言（防 sitecustomize 再抢）；
#   release       断言解析在 .releases/<hash>/src 下并记录 hash。
# 证据行（stderr，所有模式必打）：[code-source] mode=<m> llm_loop=<abs> head=<git HEAD short>
_CODE_SOURCE_MODES = ("auto", "worktree", "release")
_RELEASE_HASH_RE = re.compile(r"/\.releases/([0-9a-f]{7,40})/src/")


def _git_query(*args: str) -> str:
    """git 只读查询（失败/超时如实返回空串，不猜值）。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(_PROJECT_ROOT), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def git_head_short() -> str:
    """工作树 HEAD short hash（git 不可得时如实 'unknown'）。"""
    return _git_query("rev-parse", "--short", "HEAD") or "unknown"


def llm_loop_dirty() -> bool:
    """工作树 src/llm_loop 是否有未提交改动（`git status --porcelain -- src/llm_loop` 非空）。"""
    return bool(_git_query("status", "--porcelain", "--", "src/llm_loop"))


def path_is_under(path: Path | str, parent: Path | str) -> bool:
    """path（resolve 后）是否位于 parent 目录之下（含相等）。纯函数。"""
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
    except ValueError:
        return False
    return True


def worktree_path_preparation(repo_root: Path, sys_path: list[str] | None = None) -> tuple[str, bool]:
    """worktree 模式的 sys.path 准备（纯函数，R2/T1）。

    返回 (待插到 sys.path[0] 的绝对路径, sys.path[0] 是否已就位)。
    **刻意不读 os.environ / LFL_WORKSPACE_ROOT**：worktree 显式模式以 REPO 为
    唯一真源——即便环境已被 sitecustomize/PYTHONPATH 指向 .releases 假 release，
    准备结果仍是 <repo>/src（插入后压住注入路径，解析面归工作树）。
    ``sys_path`` 缺省取 sys.path（真跑路径），测试可传列表副本（不触发真实 import）。
    """
    src = str(Path(repo_root).resolve() / "src")
    cur = list(sys.path) if sys_path is None else list(sys_path)
    return src, bool(cur) and cur[0] == src


def worktree_check_error(llm_loop_file: Path | str, repo_root: Path | str) -> str | None:
    """worktree 断言（纯函数，R2）：解析处不在 <repo>/src 下 → 返回醒目错误文本，否则 None。"""
    expected = Path(repo_root).resolve() / "src"
    actual = Path(llm_loop_file).resolve()
    if path_is_under(actual, expected):
        return None
    return (
        "＊＊＊ --code-source=worktree 断言失败 ＊＊＊\n"
        f"  期望 llm_loop 解析于: {expected}\n"
        f"  实际解析于        : {actual}\n"
        "  已把 <repo>/src 插到 sys.path[0] 仍解析到别处——通常是被 sitecustomize/"
        "PYTHONPATH 注入的路径抢先（release 快照旧代码），或 <repo>/src 缺 llm_loop 包。\n"
        "  显式模式必须测你想测的代码，拒绝继续。"
    )


def release_hash_of(llm_loop_file: Path | str) -> str | None:
    """从 llm_loop 实际解析路径提取 `.releases/<hash>/src` 的 hash（纯函数，R3/T3）；不在则 None。"""
    m = _RELEASE_HASH_RE.search(str(Path(llm_loop_file)))
    return m.group(1) if m else None


def release_check_error(llm_loop_file: Path | str) -> str | None:
    """release 断言（纯函数，R3/T3）：解析处不在任何 .releases/<hash>/src 下 → 错误文本，否则 None。"""
    if release_hash_of(llm_loop_file) is not None:
        return None
    return (
        "＊＊＊ --code-source=release 断言失败 ＊＊＊\n"
        f"  llm_loop 实际解析于: {Path(llm_loop_file).resolve()}\n"
        "  不在任何 .releases/<hash>/src 下——release 口径要求环境已指向 release 快照"
        "（如 LFL_WORKSPACE_ROOT=.releases/<hash> + sitecustomize 注入）。\n"
        "  拒绝继续：release 口径必须钉在快照 hash 上。"
    )


def drift_warning_text(llm_loop_file: Path | str, repo_root: Path | str, dirty: bool) -> str | None:
    """auto 漂移告警（纯函数，R4/T2）——本轮事故的探测器。

    条件（同时成立才告警）：解析到的 llm_loop 不在 <repo>/src 下 **且** 工作树
    src/llm_loop 有未提交改动 → 返回两路径并列的告警文本；否则 None（auto 不硬拦）。
    """
    src = Path(repo_root).resolve() / "src"
    actual = Path(llm_loop_file).resolve()
    if path_is_under(actual, src) or not dirty:
        return None
    return (
        "!!!!!!!!!!!!!!!!!! 代码源漂移 WARNING（--code-source=auto）!!!!!!!!!!!!!!!!!!\n"
        f"  llm_loop 实际解析于（非工作树）: {actual}\n"
        f"  工作树 src（含未提交改动）    : {src}\n"
        "  → 本轮评测加载的是 release/外部代码，工作树的 src/llm_loop 未提交改动"
        "没有参与——\"测的不是你以为的代码\"。\n"
        "    如确要此口径请用 --code-source=release；要测工作树改动请用 --code-source=worktree。"
    )


def snapshot_warning_text(llm_loop_file: Path | str) -> str | None:
    """auto 快照告警（纯函数，R4 补口）——历史"测错代码"事故的静默面.

    漂移告警（drift_warning_text）只在树脏时触发；干净树解析到 `.releases/<hash>/src`
    快照时同样"测的不是工作树代码"却无任何提示。本函数对快照解析**无条件**返回
    单行告警文本（含解析路径与"非工作树代码"提示）；不在快照下 → None。
    """
    if release_hash_of(llm_loop_file) is None:
        return None
    actual = Path(llm_loop_file).resolve()
    return (
        f"[code-source] WARNING: llm_loop 实际解析于 .releases 快照（非工作树代码）: {actual}"
        "——auto 模式本轮评测加载的是 release 快照而非工作树；确要此口径请用"
        " --code-source=release，要测工作树请用 --code-source=worktree。"
    )


def build_code_source_meta(
    mode: str,
    llm_loop_path: Path | str,
    repo_head: str,
    dirty: bool,
    release_hash: str | None = None,
) -> dict:
    """run 级 meta.code_source（R5/T4，纯函数；与 knowledge_store 同级随 report 落盘）。"""
    return {
        "mode": mode,
        "llm_loop_path": str(llm_loop_path),
        "release_hash": release_hash,
        "repo_head": repo_head,
        "dirty_llm_loop": bool(dirty),
    }


def resolve_code_source(mode: str) -> dict:
    """按 --code-source 解析代码源：插路径 → import llm_loop → 断言/告警 → stderr 证据行。

    必须在 main() 的**任何** llm_loop import（含 load_env_file）之前调用（R2：
    路径准备先行；本函数是全脚本首个 llm_loop import 点）。断言失败 SystemExit
    醒目退出（worktree/release 显式模式）；auto 漂移只告警不拦（R4）；dry 与真实
    路径同经此处（R6）。返回 meta dict（R5）。
    """
    if mode == "worktree":
        src, already = worktree_path_preparation(_PROJECT_ROOT)
        if not already:
            sys.path.insert(0, src)
    import llm_loop  # noqa: E402 — 首个 llm_loop import：必须在路径准备之后

    llm_loop_path = Path(llm_loop.__file__).resolve()
    if mode == "worktree":
        err = worktree_check_error(llm_loop_path, _PROJECT_ROOT)
        if err:
            print(err, file=sys.stderr, flush=True)
            raise SystemExit(3)
    release_hash: str | None = None
    if mode == "release":
        err = release_check_error(llm_loop_path)
        if err:
            print(err, file=sys.stderr, flush=True)
            raise SystemExit(3)
        release_hash = release_hash_of(llm_loop_path)
    head = git_head_short()
    dirty = llm_loop_dirty()
    if mode == "auto":
        snap_warn = snapshot_warning_text(llm_loop_path)
        if snap_warn:
            print(snap_warn, file=sys.stderr, flush=True)
        warn = drift_warning_text(llm_loop_path, _PROJECT_ROOT, dirty)
        if warn:
            print(warn, file=sys.stderr, flush=True)
    print(f"[code-source] mode={mode} llm_loop={llm_loop_path} head={head}", file=sys.stderr, flush=True)
    return build_code_source_meta(mode, llm_loop_path, head, dirty, release_hash)


def load_scenarios(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data.get("scenarios"), list) or not data["scenarios"]:
        raise ValueError(f"评测集为空或格式错误: {path}")
    return data


_SCENARIOS_DEFAULT = Path(__file__).resolve().parent.parent / "tests" / "eval_sets" / "scenarios_v1.json"


_DEFAULT_MODEL_REF = "deepseek-v4-flash"


def resolve_model_ref() -> str:
    """本次评测**实际使用**的模型标识（provider/model），全脚本唯一真源。

    2026-10-23 修正（v5.1，独立审查 P1-2）：此前"引擎用什么模型"与
    "场景 ${MODEL} 注入什么模型"是两处独立的 ``os.environ.get`` 读取
    （一处带默认值、一处不带）→ 可能在无人察觉的情况下**静默错配**
    （判据比对的身份不是本轮真在跑的模型）。
    → 统一到这一个函数，引擎、provider 解析、场景注入共用同一结果。
    """
    import os

    return (os.environ.get("LLM_MODEL") or _DEFAULT_MODEL_REF).strip()


def substitute_model_params(scenarios: dict) -> None:
    """把场景 params 里的 ``${MODEL}`` 占位替换成**本次实际使用的模型**（就地修改）。

    2026-10-23 修正（v5）：``identity_verified`` 场景原把 ``expected`` 写死成
    ``deepseek-v4-flash``，而本轮被测模型是 ``minimax/MiniMax-M3.1-Flash``
    → 模型如实核验身份并正确作答，却因"身份与回执不一致"被判不通过（**假阴性**）。
    → 改为占位符 + 运行时按实际模型注入，场景集不再与具体模型绑死。
    """
    model_ref = resolve_model_ref()
    for sc in scenarios.get("scenarios", []):
        params = sc.get("params")
        if isinstance(params, dict) and params.get("expected") == "${MODEL}":
            params["expected"] = model_ref


def _resolve_api_key() -> str:
    """按 provider 声明的 api_key_env 解析真实 LLM 凭据（2026-10-23）.

    顺序：registry 中 provider 的 api_key_env → DEEPSEEK_API_KEY → LLM_API_KEY。
    解析 provider 时用 LLM_MODEL 的 provider 前缀；无法解析时退化为后两者。
    """
    import os
    import shutil
    import tempfile

    env_names: list[str] = []
    model_ref = resolve_model_ref()
    if model_ref and "/" in model_ref:
        provider_id = model_ref.split("/", 1)[0]
        try:
            from llm_loop.config import Settings
            from llm_loop.llm.providers import load_registry

            tmp = Path(tempfile.mkdtemp(prefix="eval-keyprobe-"))
            tmp_data = tmp / "data"
            tmp_data.mkdir(parents=True, exist_ok=True)
            src_providers = Path(__file__).resolve().parent.parent / "data" / "providers.json"
            if src_providers.exists():
                shutil.copy2(src_providers, tmp_data / "providers.json")
            reg = load_registry(
                Settings(
                    llm_api_key="probe",
                    llm_base_url="https://api.deepseek.com/v1",
                    llm_model=model_ref,
                    data_dir=str(tmp_data),
                )
            )
            spec = reg.providers.get(provider_id)
            if spec is not None and spec.api_key_env:
                env_names.append(spec.api_key_env)
        except Exception:  # noqa: BLE001 — 探测失败不改变后续行为
            pass
    env_names += ["DEEPSEEK_API_KEY", "LLM_API_KEY"]
    for name in env_names:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _product_default_max_iterations() -> int:
    """产品默认轮数预算（评测基准预算的唯一真源，预算对齐）.

    与 Settings.from_env() 同口径读 LLM_MAX_ITERATIONS（main 里 load_env_file()
    之后进程环境已含 .env 值且行内注释已剥离，进程环境优先）；未设置/脏值时
    回落 Settings 数据类字段默认（与 runtime.toml 的 max_iterations = 500 同源）。
    不构造完整 Settings：from_env 需要 api_key 且做大量路径解析，评测只取这
    一个 int——最小侵入，不引入额外失败面。
    """
    import dataclasses
    import os

    raw = os.environ.get("LLM_MAX_ITERATIONS", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass  # 脏值如实回落字段默认（与 from_env 的 env_int 容错一致），不猜
    from llm_loop.config import Settings

    for f in dataclasses.fields(Settings):
        if f.name == "max_iterations" and f.default is not dataclasses.MISSING:
            return int(f.default)
    return 500  # 兜底（与 runtime.toml 同源）；字段存在时正常不可达


def _settings(tmp_path, key: str, max_iterations: int | None = None):
    """真实 LLM Settings（对齐 test_real_llm_smoke._real_llm_settings 口径）.

    ``max_iterations``：预算对齐后缺省 None = 产品默认
    （_product_default_max_iterations：LLM_MAX_ITERATIONS → Settings 字段默认 500），
    不再硬编码 10——评测基准预算与产品配置脱节，会把"预算不足截断"误读成
    "能力失败"（历史实测：23 样本中 10 个被 10 轮上限截断，截断率 43.5%）。
    """
    import shutil

    from llm_loop.config import Settings

    if max_iterations is None:
        max_iterations = _product_default_max_iterations()

    # M64 防污染隔离: 会话/审计写临时目录，但 providers.json 复制自真实 data/——
    # 否则多 provider 配置（如 deepseek/deepseek-v4-flash 全限定名）在 L0 合成下
    # resolve 失败"未知 provider"（2026-08-17 实测 401/未知 provider 根因）。
    tmp_data = tmp_path / "data"
    src_providers = Path(__file__).resolve().parent.parent / "data" / "providers.json"
    if src_providers.exists():
        tmp_data.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_providers, tmp_data / "providers.json")

    return Settings(
        llm_api_key=key,
        llm_base_url=__import__("os").environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        # 2026-08-17: strip 防御——shell 环境可能残留带尾随空格的 LLM_MODEL（脏值
        # 被 load_env_file 环境优先跳过覆盖），导致 resolve "模型不存在"（实测根因）。
        llm_model=resolve_model_ref(),
        data_dir=str(tmp_data),
        max_iterations=max_iterations,
        tool_timeout_s=30.0,
        thinking_mode=__import__("os").environ.get("LLM_THINKING_MODE", "enabled") != "disabled",
        reasoning_effort=__import__("os").environ.get("LLM_REASONING_EFFORT", "high"),
    )


def run_one_sample(
    prompt: str,
    workdir: Path,
    key: str,
    setup: dict | None = None,
    max_iterations: int | None = None,
    knowledge_binding: dict | None = None,
) -> dict:
    """单样本真实执行：engine.run → (trace, answer)。

    会话/数据目录全部隔离到临时目录（M64 防污染真实 data/ 的独立实现）。
    setup（场景可选）: 运行前向 engine.status 注入失败信号（对齐 M25-M28 必调整基线配置，
    仅测试基建直调 status 公共方法，产品零改动）。
    """
    import tempfile

    from llm_loop.factory import build_engine

    tmp = Path(tempfile.mkdtemp(prefix="eval-run-", dir=str(workdir)))
    settings = _settings(tmp, key, max_iterations=max_iterations)
    if knowledge_binding is not None:
        # 知识库状态显式化（2026-10-25）：样本级 knowledge/{experiences,methods}
        # + 样本自己的 data_dir（session/memory/向量缓存不跨样本共享，P1）。
        settings._extra["runtime_paths"] = per_sample_knowledge(knowledge_binding, tmp)
    engine = build_engine(settings)  # type: ignore[arg-type]
    if setup:
        _apply_setup(engine, setup)
    sid = engine.session.create()
    # R8.24-D 修订②：LFL_LEAK_GUARD_MODE 默认 fail-closed —— 无 ingress 凭据的
    # role=user 写入会被 user_ingress_guard 拒绝（engine.run 直接返回
    # "[写入被拒] … leak.channel_denied"，rounds=0，模型根本未被调用）。
    # 评测框架是**测试后门**而非人类入口，故显式签发 test_harness 凭据
    # （issue_test_ingress 为测试专用入口，spec 5.3.3-4a；生产代码禁止使用）。
    # 不改动 guard 的 fail-closed 语义，只补齐本入口的合法凭据。
    ingress = None
    try:
        from llm_loop.core.trace_leak.ingress_token import issue_test_ingress

        ingress = issue_test_ingress()
    except Exception:  # noqa: BLE001 — 凭据不可得时保持原行为，不静默改语义
        ingress = None
    result = engine.run(sid, prompt, ingress=ingress)
    trace = [
        {"name": tc.get("name", ""), "arguments": tc.get("arguments", {})}
        for tc in result.tool_calls
    ]
    return {
        "trace": trace,
        "answer": result.final_answer,
        "model_used": result.model_used,
        "rounds": result.rounds,
        "truncated": result.truncated,
        # 2026-10-23(P2 A/B): 会话 id 与隔离 data 目录回传 —— 供跑批器读事件日志
        # 统计压缩事件/归档 ref（压缩后存续率需要事件侧事实，不能只看 trace）。
        "sid": sid,
        "data_dir": str(tmp / "data"),
        # A2(2026-08-14): token 用量（prompt 开销指标；0=provider 未提供）
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
    }


def _apply_setup(engine, setup: dict) -> None:
    """场景 setup：向 engine.status 注入失败信号（对齐 M28 基线：2 FAILURE + 1 异常）.

    仅测试基建直调 status 公共方法（record_tool_history/record_exception），产品零改动。
    注入失败 fail-open（status 未装配/异常时跳过，样本照常运行）。
    EVO-20260816-4fb09dd0: setup 含 inject_guidance 时同步注入行动引导
    （"发现失败率偏高/异常 → 应调用 adjust_strategy 调整"），对齐程序给事实、AI 决策。
    """
    try:
        from llm_loop.core.message import ToolResultStatus
        from llm_loop.introspection.status import ToolHistoryItem

        status = getattr(engine, "status", None)
        if status is None:
            return
        n_fail = int(setup.get("inject_failures", 0) or 0)
        for i in range(n_fail):
            status.record_tool_history(
                ToolHistoryItem(
                    name="read_file",
                    arguments={"path": f"/no/such/eval_{i}"},
                    status=ToolResultStatus.FAILURE,
                    summary=f"[文件不存在] /no/such/eval_{i} 不存在（评测预置失败信号）",
                )
            )
        if setup.get("inject_exception"):
            status.record_exception(
                "action.tool_loop", FileNotFoundError("/no/such/eval 预置异常信号")
            )
        # B: 行动引导注入（对齐 HARNESS-04 预警模式——程序给事实，AI 决策）
        if setup.get("inject_guidance"):
            try:
                from llm_loop.core.message import Message, MessageSource

                sess = getattr(engine, "session", None)
                if sess is not None:
                    msg = Message(
                        role="system",
                        content=(
                            "[行动引导] 检测到工具失败率偏高（2 条 FAILURE）与异常记录。"
                            "若确认异常，应调用 adjust_strategy 调整相关运行参数（如 max_iterations/"
                            "timeout_s）并说明依据——检查后行动，而非仅汇报。"
                        ),
                        source=MessageSource.SYSTEM,
                        metadata={"injected_system": True},
                    )
                    with contextlib.suppress(Exception):  # noqa: BLE001 — 注入失败 fail-open
                        sess.messages.append(msg)
            except Exception:  # noqa: BLE001 — 引导注入失败 fail-open
                pass
    except Exception:  # noqa: BLE001 — 注入失败 fail-open
        pass


def run_dry_sample(
    prompt: str,
    workdir: Path,
    key: str,
    setup: dict | None = None,
    max_iterations: int | None = None,
) -> dict:
    """dry 模式：固定 fixture 轨迹验证管道（零 LLM；trace 含自查+调整，answer 提及工具名）.

    ``max_iterations`` 与 run_one_sample 同签名（dry 不实际跑 LLM，仅保持调用一致）。
    """
    return {
        "trace": [
            {"name": "architecture_status", "arguments": {}},
            {"name": "adjust_strategy", "arguments": {"max_iterations": 8}},
            {"name": "read_file", "arguments": {"path": "data/eval_probe.txt"}},
        ],
        "answer": "我通过 architecture_status 自查发现失败率偏高，已用 adjust_strategy 将 max_iterations 从 5 调整为 8。",
        "model_used": "dry-fixture",
        "rounds": 3,
        "truncated": False,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def _dry_injection_selfcheck() -> None:
    """P2-5(2026-08-15): dry 模式注入可见性自检（管道失效如实失败，防 dry 假绿）.

    背景: run_one_sample 依赖 setup 向 engine.status 注入 FAILURE 历史/异常（供
    adjust_step 等必调整场景），而 run_dry_sample 完全不经过注入——若注入链路或
    architecture_status 快照生产路径失效，依赖注入的场景在 dry 下无法被发现。

    自检流程（与 run_one_sample 完全相同的注入调用 + 真实快照生产路径）:
    1. 构造真实 ArchitectureStatusProvider（architecture_status 所用的状态类）
    2. 执行 inject_failures=2 + inject_exception=True 的注入调用（复用 _apply_setup）
    3. 走 architecture_status 快照生产路径（run_status → status_provider.snapshot）
    4. 断言注入的 FAILURE 计数与异常在快照中可见；不可见抛 RuntimeError
       （dry 结果不可信时必须如实失败，不静默通过）。
    """
    from types import SimpleNamespace

    from llm_loop.core.message import ToolResultStatus
    from llm_loop.introspection.status import ArchitectureStatusProvider
    from llm_loop.introspection.tools_status import run_status

    status = ArchitectureStatusProvider(enabled=True)
    _apply_setup(
        SimpleNamespace(status=status),
        {"inject_failures": 2, "inject_exception": True},
    )

    result = run_status(
        ctx=None,
        status_provider=status,
        args={
            "dimensions": ["tool_history", "exception_log"],
            # Dry selfcheck deliberately validates process-global injected fixtures rather
            # than a human task session; make that authority explicit instead of widening
            # model-facing current_session semantics.
            "scope": "runtime",
        },
    )
    if result.status != ToolResultStatus.SUCCESS:
        raise RuntimeError(
            f"dry 注入自检失败: architecture_status 快照生产失败（status={result.status.value}）"
        )
    try:
        snap = json.loads(result.content)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"dry 注入自检失败: architecture_status 快照解析失败: {exc}") from exc

    tool_history = snap.get("tool_history", [])
    failures = [t for t in tool_history if t.get("status") == ToolResultStatus.FAILURE.value]
    exception_log = snap.get("exception_log", [])
    if len(failures) < 2 or not exception_log:
        raise RuntimeError(
            "dry 注入自检失败: 预置失败信号在 architecture_status 快照中不可见"
            f"（tool_history FAILURE={len(failures)}/2, exception_log={len(exception_log)}/1）"
            "——注入链路或快照生产路径失效，dry 结果不可信（如实失败）。"
        )


def _atomic_write_text(path: Path, text: str) -> None:
    """原子写文本（先写临时文件再 replace）：中断不产生半截报告."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _load_checkpoint(path: Path | None) -> dict[tuple[str, int], dict]:
    """读回已完成的样本记录（键 = (scenario_id, sample_index) → 样本详情）.

    2026-10-23：长跑批（84 样本真实 LLM）此前**只在 84 样本全跑完后**才写
    report.json，中途被 kill 即全部产出丢失（实测 evals/results/
    eval_v2_m31flash_20261023/ 为空 = 零产出）。本函数配合逐样本 checkpoint
    实现断点续跑。
    末行可能因中断被截断 → JSON 解析失败如实跳过该行（不静默改写已完成语义）。
    """
    done: dict[tuple[str, int], dict] = {}
    if path is None or not path.exists():
        return done
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        sid = rec.get("scenario_id")
        idx = rec.get("sample")
        detail = rec.get("detail")
        if sid is None or idx is None or not isinstance(detail, dict):
            continue
        try:
            done[(str(sid), int(idx))] = detail
        except (TypeError, ValueError):
            continue
    return done


def _append_checkpoint(path: Path, scenario_id: str, sample_index: int, detail: dict) -> None:
    """追加一条样本记录并 flush（逐样本落盘 → 中断只丢当前样本）."""
    rec = {"scenario_id": scenario_id, "sample": sample_index, "detail": detail}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()


def _resolve_run_budget(
    scenarios: dict,
    *,
    product_default: int,
    profile: str,
    ignore_scenario_pins: bool,
    force_max_iterations: int | None,
) -> dict:
    """解析本次跑批的轮数预算 → budget 对账块（纯函数，不改场景数据）.

    两个正交开关（预算对齐设计，勿合并语义）:
    - profile 只决定**基准预算**: product=产品默认; pinned10=10（复现历史跑批）。
      域内 scenarios_v1 有多步链式场景依赖 pin（如 20 轮），基准不一刀切覆盖 pin。
    - ignore_scenario_pins 只决定**是否忽略场景 pin**
      （held-out A 级口径: --budget-profile product --ignore-scenario-pins）。
    - --max-iterations（force）优先级最高：覆盖基准且忽略 pin（保留旧行为语义）。
    """
    if force_max_iterations is not None:
        base = int(force_max_iterations)
        pins_honored = False
    elif profile == "pinned10":
        base = 10
        pins_honored = not ignore_scenario_pins
    else:
        base = int(product_default)
        pins_honored = not ignore_scenario_pins
    scenario_pins: dict[str, int] = {}
    effective: dict[str, int] = {}
    for sc in scenarios.get("scenarios", []):
        sid = str(sc.get("id", ""))
        pin = sc.get("max_iterations")
        if pin is not None:
            scenario_pins[sid] = int(pin)
        effective[sid] = scenario_pins[sid] if (pins_honored and sid in scenario_pins) else base
    return {
        "product_default": int(product_default),
        "base": base,
        "profile": profile,
        "scenario_pins": scenario_pins,
        "pins_honored": pins_honored,
        "effective_by_scenario": effective,
    }


@_sealed_batch
def evaluate(
    scenarios: dict,
    *,
    dry: bool,
    samples_override: int | None,
    workdir: Path,
    checkpoint_path: Path | None = None,
    resume: bool = False,
    budget: dict | None = None,
    knowledge_binding: dict | None = None,
    code_source: dict | None = None,
) -> dict:
    # verdicts 延迟 import（R2）：模块级 import 会在 --code-source 路径准备之前
    # 锁定解析面；此处 import 时 resolve_code_source 已完成路径准备与断言。
    from llm_loop.eval.verdicts import run_verdict, wilson_ci

    key = ""
    if not dry:
        # 2026-10-23: key 来源按 **provider 实际使用的 api_key_env** 解析，
        # 不再只认 DEEPSEEK_API_KEY/LLM_API_KEY —— 否则换 provider（如 minimax）
        # 时 registry 取不到凭据，client_params 抛 "缺少 api_key"。
        # 解析顺序：provider 声明的 api_key_env → DEEPSEEK_API_KEY → LLM_API_KEY。
        key = _resolve_api_key()
        if not key:
            raise RuntimeError(
                "无真实 LLM key（provider 声明的 api_key_env / DEEPSEEK_API_KEY / LLM_API_KEY）；"
                "使用 --dry 验证管道"
            )
    else:
        # P2-5(2026-08-15): dry 路径开头做注入可见性自检——adjust_step 等依赖预置失败
        # 信号的场景必须在 dry 下同样可被发现（注入不可见 → 如实失败，防 dry 假绿）
        _dry_injection_selfcheck()

    if budget is None:
        # 兼容旧调用（不传 budget）：默认产品口径（基准=产品默认，pin honored）。
        budget = _resolve_run_budget(
            scenarios,
            product_default=_product_default_max_iterations(),
            profile="product",
            ignore_scenario_pins=False,
            force_max_iterations=None,
        )

    runner = run_dry_sample if dry else run_one_sample
    results: list[dict] = []
    # 断点续跑：已完成的 (scenario_id, sample_index) 直接复用，不再调 LLM。
    # 复用样本的 verdict 是**上次真实运行**的判定结果，不重算（重算需再跑 LLM）。
    done = _load_checkpoint(checkpoint_path) if resume else {}
    if done:
        print(f"[resume] 复用已完成样本 {len(done)} 条", flush=True)
    substitute_model_params(scenarios)
    # 封条：跑批全程置 env（域内跑批同样无害 → 覆盖所有模式，不只 held-out）。
    # 覆盖整个样本循环：单样本抛错也要复原，不得把封条漏到进程后续操作里。
    for sc in scenarios["scenarios"]:
        n = samples_override if samples_override is not None else int(sc.get("samples", 6))
        setup = sc.get("setup")
        # 场景级轮数预算（预算对齐）：基准由 budget 块给出（profile=product/pinned10），
        # 场景可写 "max_iterations" pin 覆盖基准 → 多步链式场景不被基准截断；
        # --ignore-scenario-pins 时忽略 pin，全部用基准。不再硬编码 10。
        sc_max_iter = int(budget["effective_by_scenario"].get(str(sc["id"]), budget["base"]))
        per_scenario: list[dict] = []
        for i in range(n):
            ck_key = (str(sc["id"]), i + 1)
            if ck_key in done:
                per_scenario.append(done[ck_key])
                continue
            if dry:
                sample = runner(sc["prompt"], workdir, key, setup, sc_max_iter)
            else:
                sample = runner(
                    sc["prompt"],
                    workdir,
                    key,
                    setup,
                    sc_max_iter,
                    knowledge_binding=knowledge_binding,
                )
            verdict = run_verdict(sc["verdict"], sample["trace"], sample["answer"], sc.get("params"))
            detail = {
                "sample": i + 1,
                "verdict": bool(verdict),
                "trace": sample["trace"],
                "answer_head": sample["answer"][:200],
                # 2026-10-23：存全量答复（此前只留 200 字摘要 → 判据口径变更后**无法离线重判**，
                # 每次改判据都得重跑 108 条真实 LLM 样本）。
                "answer_full": sample["answer"],
                "model_used": sample["model_used"],
                "rounds": sample["rounds"],
                "truncated": sample["truncated"],
                "tokens_in": sample.get("tokens_in", 0),
                "tokens_out": sample.get("tokens_out", 0),
            }
            per_scenario.append(detail)
            # 逐样本落盘：中断只丢当前样本，不丢已跑完的部分
            if checkpoint_path is not None:
                _append_checkpoint(checkpoint_path, str(sc["id"]), i + 1, detail)
            print(
                f"[sample] {sc['id']} #{i + 1}/{n} verdict={bool(verdict)} "
                f"rounds={sample['rounds']} model={sample['model_used']}",
                flush=True,
            )
        # ── 统计口径（2026-10-23 修正）────────────────────────────────
        # 轮数耗尽（truncated）的样本**不是**被测能力的失败，是执行预算不足。
        # 但**不能因此把它们从分母里删掉** —— 那会把通过率抬高（负结果被藏起来，
        # 违反"负结果同等呈现"）。实测 v2 跑批 22 样本：9 个截断；
        #   删掉截断 → 12/13 = 92.3%（虚高）；保留全样本 → 17/22 = 77.3%（真实）
        # 口径（两个都报，不藏负结果）：
        #   主口径 rate = 通过 / 全部样本          ← 保守，作为对外结论
        #   参考 rate_scored = 通过 / (通过 + 真失败) ← 排除截断后的能力上界
        #   truncated_rate = 截断 / 全部样本        ← 预算不足的直接度量
        n_trunc = sum(1 for s in per_scenario if s.get("truncated"))
        n_pass_all = sum(1 for s in per_scenario if s["verdict"])
        n_pass_scored = sum(1 for s in per_scenario if s["verdict"] and not s.get("truncated"))
        n_fail = sum(1 for s in per_scenario if not s["verdict"] and not s.get("truncated"))
        n_scored = n_pass_scored + n_fail
        k = n_pass_all
        lo, hi = wilson_ci(k, n) if n else (0.0, 0.0)
        lo_s, hi_s = wilson_ci(n_pass_scored, n_scored) if n_scored else (0.0, 0.0)
        # A2: 场景级 token 开销统计（provider 未提供用量时如实 0）
        _toks_in = [s["tokens_in"] for s in per_scenario]
        _toks_out = [s["tokens_out"] for s in per_scenario]
        _toks_total = [a + b for a, b in zip(_toks_in, _toks_out, strict=False)]
        tokens_stats = {
            "total_in": sum(_toks_in),
            "total_out": sum(_toks_out),
            "avg_per_sample": round(sum(_toks_total) / n, 1) if n else 0,
        }
        results.append(
            {
                "id": sc["id"],
                "name": sc["name"],
                "verdict": sc["verdict"],
                "samples": n,
                "passed": k,
                "truncated": n_trunc,
                "failed": n_fail,
                "scored": n_scored,
                "tokens": tokens_stats,
                "rate": (k / n) if n else 0.0,
                "rate_scored": (n_pass_scored / n_scored) if n_scored else 0.0,
                "truncated_rate": (n_trunc / n) if n else 0.0,
                "ci": [round(lo, 3), round(hi, 3)],
                "ci_scored": [round(lo_s, 3), round(hi_s, 3)],
                "samples_detail": per_scenario,
            }
        )
    ks = knowledge_binding or {}
    return {
        "results": results,
        "dry": dry,
        "budget": budget,
        # 知识库状态基线（run 级 meta，随 report.json 落盘；per_sample_isolated:
        # 每样本独立副本，样本写入互不可见）
        "knowledge_store": {
            "mode": ks.get("mode", "empty"),
            "files": ks.get("files", 0),
            "exp_dir": ks.get("experiences", ""),
            "methods_dir": ks.get("methods", ""),
            "per_sample_isolated": True,
        },
        # 本轮是否在封条下跑的（sealed_env 取自 with 内，即跑批期实际生效值）
        # 跑批期由 _sealed_batch 置 "1"；此处即跑批期实际生效值
        "heldout_sealed": os.environ.get(_SEAL_ENV) == "1",
        # 代码源对账（R5，与 knowledge_store 同级；None=旧调用方未传 → 空块如实标注）
        "code_source": code_source if code_source is not None else {},
    }


def render_markdown(scenarios: dict, eval_out: dict) -> str:
    lines = [
        "# 评测报告（T4 评测集运行）",
        "",
        f"> 评测集: {scenarios.get('name', 'unnamed')}（version {scenarios.get('version', 'unknown')}）",
        f"> 运行模式: {'dry 管道验证（零 LLM）' if eval_out['dry'] else '真实 LLM'}",
        f"> 封条: heldout_sealed={str(bool(eval_out.get('heldout_sealed'))).lower()}"
        f"（{_SEAL_ENV}=1 仅在跑批期生效）",
        f"> 生成: {datetime.now(UTC).isoformat()}",
        f"> 基线引用: {scenarios.get('baseline_ref', '')}（各验收报告为数据唯一出处）",
    ]
    # 代码源对账（R5）：评测实际加载的 llm_loop 解析面（缺失=旧调用方，跳过不渲染）
    _cs = eval_out.get("code_source") or {}
    if _cs:
        lines.append(
            f"> code-source: mode={_cs.get('mode')} llm_loop={_cs.get('llm_loop_path')} "
            f"release={_cs.get('release_hash') or '-'} head={_cs.get('repo_head')} "
            f"dirty_llm_loop={str(bool(_cs.get('dirty_llm_loop'))).lower()}"
        )
    # 预算对账（预算对齐）：头部显式记录本次跑批的轮数预算口径；
    # 任一场景有效预算 ≠ 产品默认时必须声明 Δpass@1 不可直接迁移
    # （改预算的跑批是另一种配置，结论不得并轨）。
    b = eval_out.get("budget") or {}
    if b:
        pins_desc = ", ".join(f"{k}={v}" for k, v in b.get("scenario_pins", {}).items()) or "无"
        lines.append(
            f"> 预算: profile={b['profile']} base={b['base']} "
            f"product_default={b['product_default']} "
            f"pins_honored={str(b['pins_honored']).lower()}（scenario_pins: {pins_desc}）"
        )
        _pd = int(b["product_default"])
        off_product = sorted(
            sid for sid, v in b.get("effective_by_scenario", {}).items() if int(v) != _pd
        )
        if off_product:
            lines.append(
                f"> ⚠ 预算声明: 本跑批预算 ≠ 产品默认（product_default={_pd}；"
                f"偏离产品默认的场景: {', '.join(off_product)}）——"
                "Δpass@1 不得直接迁移为产品预算下的结论。"
            )
    lines += [
        "",
        "| 场景 | 判定 | 通过/全部 | 截断 | 真失败 | 主口径率 | 参考率(排除截断) | Wilson 95% CI(主) | 平均 token/样本 |",
        "|:---|:---|:---|:---|:---|:---|:---|:---|:---|",
    ]
    for r in eval_out["results"]:
        lines.append(
            f"| {r['name']} | {r['verdict']} | {r['passed']}/{r['samples']} "
            f"| {r.get('truncated', 0)} | {r.get('failed', 0)} "
            f"| {r['rate']:.2f} | {r.get('rate_scored', 0.0):.2f} "
            f"| [{r['ci'][0]:.3f}, {r['ci'][1]:.3f}] "
            f"| {r.get('tokens', {}).get('avg_per_sample', 0):.0f} |"
        )
    lines.append("")
    lines.append(
        "> 口径（2026-10-23 修正）：**主口径率 = 通过 / 全部样本**（保守，对外结论用）；"
        "「截断」= 达到最大轮数被中断的样本，单列且**仍计入全样本分母** —— "
        "轮数耗尽是执行预算不足而非能力失败，但把它从分母删掉会让通过率虚高、藏掉负结果。"
        "「参考率」= 通过 / (通过 + 真失败)，是排除截断后的能力上界；两者同报，不藏负结果。"
    )
    lines.append(
        "> 纪律：样本不足如实标注；CI 区间重叠即不宣称统计显著；负结果同等呈现。"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T4 评测集运行器（真实 LLM / dry 管道验证）")
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=_SCENARIOS_DEFAULT,
    )
    parser.add_argument("--samples", type=int, default=None, help="覆盖场景样本数（默认用场景定义值）")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="报告输出目录（默认 docs/metrics/eval_<ts>/，自动创建）",
    )
    parser.add_argument("--dry", action="store_true", help="dry 模式：fixture 轨迹验证管道（零 LLM）")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="逐样本 checkpoint 路径（默认 <output>/checkpoint.jsonl）：每样本跑完即落盘，"
        "中断后可 --resume 续跑（2026-10-23 长跑批中断零产出修复）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="断点续跑：复用 checkpoint 中已完成的样本，只跑未完成部分",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="只跑这些场景（逗号分隔的 scenario id）——用于针对性补跑",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help=(
            "覆盖场景的 max_iterations（针对性补跑用）：优先级高于 --budget-profile 与场景 pin。"
            "改了预算的跑批是**另一种配置**，报告里必须单列，不得并进主跑批的分母"
        ),
    )
    parser.add_argument(
        "--budget-profile",
        choices=["product", "pinned10"],
        default="product",
        help=(
            "轮数预算口径（决定**基准预算**）: product=产品默认"
            "（LLM_MAX_ITERATIONS/Settings.max_iterations，缺省 500，默认值）；"
            "pinned10=10（复现历史跑批行为）。与 --ignore-scenario-pins 正交"
        ),
    )
    parser.add_argument(
        "--ignore-scenario-pins",
        action="store_true",
        help=(
            "忽略场景文件里的 max_iterations pin，全部场景用基准预算"
            "（held-out A 级跑批口径: --budget-profile product --ignore-scenario-pins）。"
            "与 --budget-profile 正交"
        ),
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help=(
            "scratch 根目录（默认系统临时目录 <tmp>/lfl-e2e，**不写仓库**）。"
            "每轮跑批在根下建独立 eval-scratch-* 子目录，结束默认删除"
        ),
    )
    parser.add_argument(
        "--keep-scratch",
        action="store_true",
        help="保留本轮 scratch 目录（默认删除；排查失败样本时用）",
    )
    parser.add_argument(
        "--knowledge-store",
        default="empty",
        help=(
            "知识库状态基线: empty=每样本空目录（默认，零知识基线，与历史跑批同质）；"
            "snapshot=生产 experiences/ 与 data/methods/ 深拷贝后逐样本再复制"
            "（与生产同质的对照轮；写入不回流生产）。"
        ),
    )
    parser.add_argument(
        "--code-source",
        choices=list(_CODE_SOURCE_MODES),
        default="auto",
        help=(
            "评测实际加载的 llm_loop 代码源（stderr 必打证据行 + meta 记录实路径）: "
            "auto=继承当前环境（sitecustomize/PYTHONPATH 指哪算哪，默认；解析不在"
            "工作树且工作树有未提交 src/llm_loop 改动时打 WARNING，不拦）；"
            "worktree=把 <repo>/src 插到 sys.path[0] 并断言 llm_loop 解析于工作树"
            "（防 sitecustomize/PYTHONPATH 抢解析面）；release=断言解析在 "
            ".releases/<hash>/src 快照下并记录 hash。dry 与真实路径同受约束。"
        ),
    )
    args = parser.parse_args(argv)
    if args.knowledge_store == "production":
        parser.error(
            "--knowledge-store=production 已移除：factory 的 Settings-env 解析不读"
            " os.environ，并无生产泄漏可堵；需要生产同质知识库请改用 snapshot"
        )
    if args.knowledge_store not in _KNOWLEDGE_MODES:
        parser.error(f"--knowledge-store 必须是 {'/'.join(_KNOWLEDGE_MODES)}")

    # 代码源显式化（R1-R6）：必须在 main() 的任何 llm_loop import（含下一行
    # load_env_file）之前完成路径准备与断言——更早的 import 会锁定解析面，
    # --code-source 将失效（R2）。dry 与真实路径同经此处（R6）。
    code_source_meta = resolve_code_source(args.code_source)

    # M63 对齐: 与 CLI/Web/飞书一致从项目 .env 加载（环境变量优先），
    # 真实模式无需手动 export key；--dry 不受影响（不读 key）
    from llm_loop.config import load_env_file

    load_env_file()

    # scratch 兜底：正常/异常都在 finally 删本次 run 目录（--keep-scratch 保留）。
    run_scratch: Path | None = None

    try:
        scenarios = load_scenarios(args.scenarios)
        if args.only:
            keep = {s.strip() for s in str(args.only).split(",") if s.strip()}
            known = {s.get("id") for s in scenarios["scenarios"]}
            missing = keep - known
            if missing:
                raise SystemExit(f"--only 指定了不存在的场景: {sorted(missing)}")
            scenarios = {
                **scenarios,
                "scenarios": [s for s in scenarios["scenarios"] if s.get("id") in keep],
            }
        # 预算对齐（在 load_env_file() 之后解析 → LLM_MAX_ITERATIONS 已含 .env 值）:
        # 基准预算由 --budget-profile 决定（product=产品默认 / pinned10=10），
        # 场景 pin 默认 honored，--ignore-scenario-pins 时忽略；
        # --max-iterations 显式覆盖优先级最高（保留旧补跑语义）。不改场景数据。
        budget = _resolve_run_budget(
            scenarios,
            product_default=_product_default_max_iterations(),
            profile=args.budget_profile,
            ignore_scenario_pins=args.ignore_scenario_pins,
            force_max_iterations=args.max_iterations,
        )
        # scratch 根：默认系统临时目录（不再写仓库 data/e2e）；--workdir 显式覆盖。
        scratch_root = args.workdir or _SCRATCH_ROOT
        scratch_root.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        out_dir = args.output or (Path(__file__).resolve().parent.parent / "docs" / "metrics" / f"eval_{ts}")
        out_dir.mkdir(parents=True, exist_ok=True)
        ck_path = args.checkpoint or (out_dir / "checkpoint.jsonl")
        ck_path.parent.mkdir(parents=True, exist_ok=True)
        # 每轮跑批独立 scratch 子目录（临时目录下），finally 清理
        run_scratch = Path(tempfile.mkdtemp(prefix="eval-scratch-", dir=str(scratch_root)))
        print(
            f"[scratch] {run_scratch}（结束后默认删除，--keep-scratch 保留）",
            flush=True,
        )
        binding = prepare_knowledge_binding(run_scratch, args.knowledge_store)
        print(
            f"[knowledge-store] mode={binding['mode']} files={binding['files']} "
            f"exp={binding['experiences']} methods={binding['methods']}",
            file=sys.stderr,
            flush=True,
        )
        eval_out = evaluate(
            scenarios,
            dry=args.dry,
            samples_override=args.samples,
            workdir=run_scratch,
            checkpoint_path=ck_path,
            resume=args.resume,
            budget=budget,
            knowledge_binding=binding,
            code_source=code_source_meta,
        )
        print(
            f"[seal] heldout_sealed={str(bool(eval_out.get('heldout_sealed'))).lower()}"
            f"（{_SEAL_ENV}=1 仅在跑批期生效，已恢复原值）",
            flush=True,
        )
        _atomic_write_text(
            out_dir / "report.json",
            json.dumps(
                {"scenario_version": scenarios.get("version", "unknown"), "generated": ts, **eval_out},
                ensure_ascii=False,
                indent=2,
            ),
        )
        _atomic_write_text(out_dir / "report.md", render_markdown(scenarios, eval_out))
        print(f"评测完成（{'dry' if args.dry else 'real'}）: {out_dir}")
        for r in eval_out["results"]:
            print(f"  {r['name']}: {r['passed']}/{r['samples']} = {r['rate']:.2f} CI {r['ci']}")
        return 0
    except RuntimeError as exc:
        print(f"评测中止: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — 异常如实报错退出
        print(f"评测异常: {exc}", file=sys.stderr)
        return 1
    finally:
        # scratch 只对本轮有意义：默认删除（异常路径同样清理），避免临时目录无限增长。
        if run_scratch is not None:
            if args.keep_scratch:
                print(f"[scratch] 保留: {run_scratch}（--keep-scratch）", file=sys.stderr)
            else:
                shutil.rmtree(run_scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
