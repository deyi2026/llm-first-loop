#!/usr/bin/env python3
"""R9 函数规模基线重登记脚本（EVO-20261025-e0bff8ee，人工批准执行）.

度量**必须复用守卫自己的口径**：import ``tests/unit/test_arch_guards.py`` 的
``_measure_functions``（AST 行数 = end_lineno - lineno + 1 + 双口径读源），
不另写第二套 AST——避免双口径漂移。只重登记函数规模两节：

- ``function_lines``：实测 ≥ INCLUDE_THRESHOLD(120) 的全部键 + 既有存活
  历史小键（<120 但仍存在的登记键——承载"曾经很大"的棘轮锚，不因变小失锚）；
- ``legacy_super_functions``：实测 > GLOBAL_FAIL(300) 的全部键。

数值一律取实测值：原本更高的登记 = 收紧；实测更高的登记 = 按实测重定
（该类抬高是 EVO-20261025-e0bff8ee 批准的红线放宽，须 guard(r9) 提交可见）。
死键（实测不存在的登记键）删除——防死键掩盖真实违规。

与函数规模无关的节（durability_registry / local_imports / known_cycles /
exemptions / kernel_import_edges / top_level_units / 计量口径 / 迁移记录）
原样保留，本脚本不触碰。

用法：
    python scripts/regen_function_size_baseline.py           # 重登记并写盘
    python scripts/regen_function_size_baseline.py --check   # 幂等校验，不一致 exit 1

输出确定性：键排序 + indent=2 + ensure_ascii=False + 末尾换行；``生成时间``
取 head_commit 的提交日（非墙钟），同一 git 状态下重复运行字节级一致。
``head_commit`` = 实测所依据的源提交 = 重登记提交的父提交（语义固化进
``_meta.说明``）。--check 只校验两函数规模节 + head_commit 形态，不重算
元数据（后续提交推进 HEAD 不影响幂等性）。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "guards" / "function_size_baseline.json"

META_DESC = (
    "R9 架构守卫基线 v2（EVO-20261025-e0bff8ee 全量重登记）。"
    "function_lines：实测 ≥120 行全量登记 + 既有存活历史小键保留（棘轮：登记值只降不升）；"
    "legacy_super_functions：实测 >300 行的超大函数（原四函数棘轮扩展为全量登记）；"
    "local_imports：文件级函数内 import 总量（只减不增，豁免仅 optional/plugin 行内标记）；"
    "known_cycles：环登记（Phase 3 断两环后清空并断言空）；exemptions：OQ-7 强约束豁免清单。"
    "head_commit = 本次实测所依据的源提交（即本提交的父提交）；所有数值 = 该提交工作树实测。"
)


def _git(*args: str) -> str:
    proc = subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _guard_module():  # noqa: ANN202 — 命名空间包导入，返回类型即 test_arch_guards 模块
    sys.path.insert(0, str(ROOT))
    from tests.unit import test_arch_guards as guards

    return guards


def _merge_registration(
    measured: dict[str, int],
    old_fl: dict[str, int],
    old_legacy: dict[str, int],
    include_threshold: int,
    global_fail: int,
) -> tuple[dict[str, int], dict[str, int]]:
    """守卫语义的重登记合并（纯函数，--check 与写盘共用同一结果保证幂等）。"""
    live_old = (set(old_fl) | set(old_legacy)) & set(measured)
    legacy = {k: measured[k] for k in sorted(measured) if measured[k] > global_fail}
    fl: dict[str, int] = {}
    for key in sorted(measured):
        lines = measured[key]
        if lines > global_fail:
            continue  # >300 只进 legacy
        if lines >= include_threshold or key in live_old:
            fl[key] = lines
    return fl, legacy


def _diff_summary(
    old_fl: dict[str, int],
    old_legacy: dict[str, int],
    new_fl: dict[str, int],
    new_legacy: dict[str, int],
) -> list[str]:
    old_all = {**old_fl, **old_legacy}
    new_all = {**new_fl, **new_legacy}
    lines = [
        f"function_lines: {len(old_fl)} → {len(new_fl)}",
        f"legacy_super_functions: {len(old_legacy)} → {len(new_legacy)}",
    ]
    deleted = sorted(set(old_all) - set(new_all))
    added = sorted(set(new_all) - set(old_all))
    raised = [
        (k, old_all[k], v, "legacy" if k in new_legacy else "fl")
        for k, v in sorted(new_all.items())
        if k in old_all and v > old_all[k]
    ]
    tightened = [(k, old_all[k], v) for k, v in sorted(new_all.items()) if k in old_all and v < old_all[k]]
    lines.append(f"删除死键 {len(deleted)} 条：")
    lines.extend(f"  ✗ {k}" for k in deleted)
    lines.append(f"新增登记 {len(added)} 条：")
    lines.extend(f"  + {new_all[k]:>4}  {k}" + ("  [legacy]" if k in new_legacy else "") for k in added)
    lines.append(f"按实测抬高 {len(raised)} 条（= EVO-20261025-e0bff8ee 批准的红线放宽，逐条可见）：")
    lines.extend(f"  ↑ {o:>4} → {n:<4} {k}（{sec}）" for k, o, n, sec in raised)
    lines.append(f"收紧 {len(tightened)} 条（登记值下降）：")
    lines.extend(f"  ↓ {o:>4} → {n:<4} {k}" for k, o, n in tightened)
    return lines


_SECTIONS: tuple[str, ...] = ("function_lines", "legacy_super_functions")
_META_FIELDS_NOTE = "_meta（head_commit/生成时间/说明）"


def _selected_sections(only: str) -> tuple[str, ...]:
    """``--only`` → 本次重登记要写的节；``all`` = 两个函数规模节全写。"""
    return _SECTIONS if only == "all" else (only,)


def _untouched_note(sections: tuple[str, ...], *, refresh_meta: bool) -> str:
    """把"本次没动哪些段"写成回执——保住"只收紧、不顺带改别段"的可验证性。"""
    untouched = [s for s in _SECTIONS if s not in sections]
    if not refresh_meta:
        untouched.append(_META_FIELDS_NOTE)
    if not untouched:
        return "本次覆盖两个函数规模节 + _meta"
    return "未触碰（字节级保留）：" + "、".join(untouched)


def _check_problems(
    current: dict,
    new_fl: dict[str, int],
    new_legacy: dict[str, int],
    sections: tuple[str, ...],
    *,
    check_meta: bool,
) -> list[str]:
    problems: list[str] = []
    if "function_lines" in sections and current.get("function_lines") != new_fl:
        problems.append("function_lines 与实测合并不一致（src 漂移未重登记，或登记被手改）")
    if "legacy_super_functions" in sections and current.get("legacy_super_functions") != new_legacy:
        problems.append("legacy_super_functions 与实测合并不一致（src 漂移未重登记，或登记被手改）")
    if check_meta:
        head = str(current.get("_meta", {}).get("head_commit", ""))
        if not re.fullmatch(r"[0-9a-f]{7,40}", head):
            problems.append(f"_meta.head_commit 非法短 sha: {head!r}")
    return problems


def _ordered_merge(old: dict[str, int], new: dict[str, int]) -> dict[str, int]:
    """保留磁盘上的键序：既有键原位替换，新键按字典序追加。

    否则整文件 ``sort_keys`` 重写会把**未选中段**的键序也挪一遍——那正是
    "只收紧会顺带改别段"的另一半问题（值没变、diff 一片红）。
    """
    ordered = {key: new[key] for key in old if key in new}
    ordered.update({key: value for key, value in sorted(new.items()) if key not in ordered})
    return ordered


def _apply_sections(
    current: dict,
    new_fl: dict[str, int],
    new_legacy: dict[str, int],
    sections: tuple[str, ...],
    *,
    refresh_meta: bool,
) -> dict:
    """整文件写回的唯一构造点：未选中的节原样带到新 dict（值 + 键序）。"""
    updated = dict(current)
    if "function_lines" in sections:
        updated["function_lines"] = _ordered_merge(
            dict(current.get("function_lines", {})), new_fl
        )
    if "legacy_super_functions" in sections:
        updated["legacy_super_functions"] = _ordered_merge(
            dict(current.get("legacy_super_functions", {})), new_legacy
        )
    if refresh_meta:
        meta = dict(current.get("_meta", {}))
        meta["head_commit"] = _git("rev-parse", "--short", "HEAD")
        meta["生成时间"] = _git("show", "-s", "--format=%cs", "HEAD")
        meta["说明"] = META_DESC
        updated["_meta"] = meta
    return updated


def main() -> int:
    ap = argparse.ArgumentParser(description="R9 函数规模基线重登记（守卫单口径）")
    ap.add_argument("--check", action="store_true", help="只校验不写盘：不一致 exit 1")
    ap.add_argument(
        "--only",
        choices=(*_SECTIONS, "all"),
        default="all",
        help="只重登记指定节；非 all 时 _meta 原样保留（只收紧、不顺带改别段）",
    )
    ap.add_argument("--dry-run", action="store_true", help="只打印差异摘要，不写盘")
    args = ap.parse_args()

    sections = _selected_sections(args.only)
    refresh_meta = args.only == "all"
    guards = _guard_module()
    measured = guards._measure_functions()  # noqa: SLF001 — 刻意复用守卫口径（见模块 docstring）
    current = json.loads(BASELINE.read_text(encoding="utf-8"))
    old_fl = dict(current.get("function_lines", {}))
    old_legacy = dict(current.get("legacy_super_functions", {}))
    new_fl, new_legacy = _merge_registration(
        measured, old_fl, old_legacy, guards.INCLUDE_THRESHOLD, guards.GLOBAL_FAIL
    )

    if args.check:
        problems = _check_problems(
            current, new_fl, new_legacy, sections, check_meta=refresh_meta
        )
        if problems:
            print("基线未处于重登记幂等态：")
            for p in problems:
                print(f"  - {p}")
            print(
                "修复：python scripts/regen_function_size_baseline.py"
                f" --only {args.only}（guard(r9): 前缀提交）"
            )
            return 1
        scope = "全部函数规模节" if args.only == "all" else args.only
        suffix = "" if refresh_meta else "；_meta 不在本次校验范围"
        print(f"OK: {scope}与守卫实测一致（幂等）{suffix}")
        return 0

    updated = _apply_sections(
        current, new_fl, new_legacy, sections, refresh_meta=refresh_meta
    )
    print(_untouched_note(sections, refresh_meta=refresh_meta))
    if args.dry_run:
        print("--dry-run：未写盘，以下为将要写入的差异")
    else:
        BASELINE.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"已重登记 {BASELINE.relative_to(ROOT)}")
    for line in _diff_summary(old_fl, old_legacy, new_fl, new_legacy):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
