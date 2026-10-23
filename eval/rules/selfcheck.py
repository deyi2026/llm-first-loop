#!/usr/bin/env python3
"""评测文档与产物自检（只读、可复算）。

用途：把 `docs/EVAL-PLAN-LFL-20261023.md` §14 的自检表与 §15/§16 的数字断言
      固化成脚本，使后续每次改文档/改评测都能跑一次，防止数字漂移。

用法：
    python3 eval/rules/selfcheck.py            # 全部检查
    python3 eval/rules/selfcheck.py --json     # 机器可读

退出码：0 = 全部通过；1 = 存在 FAIL（断言与事实不符）；2 = 输入缺失。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# 2026-10-23（known-red §13）：显式把工作树 `src` 插到 sys.path 最前。
# 否则 `import llm_loop` 会落到本机 PYTHONPATH 指向的 .releases 快照，
# 导致自检验证的是 release 快照而非当前工作树（本地代码改动静默失效）。
sys.path.insert(0, os.path.join(ROOT, "src"))
PLAN = "docs/EVAL-PLAN-LFL-20261023.md"
BASE = "eval/baselines/baseline_v0.md"
RULES_STAT = "eval/rules/statistics.md"
RULES_HOLD = "eval/rules/holdout.md"
REDS = "docs/known-reds-20260909.md"
RESULTS = "eval/results/baseline_v0_terminus2_glm53_full/2026-10-14__20-23-44/results.json"
LOG = "eval/logs/baseline_v0_full.log"


class Checker:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append((name, "PASS" if ok else "FAIL", detail))
        return ok

    def file_exists(self, name: str, rel: str) -> bool:
        return self.check(f"文件存在: {rel}", os.path.exists(os.path.join(ROOT, rel)), rel)

    def text_in(self, name: str, rel: str, needle: str, must: bool = True) -> bool:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            return self.check(name, False, f"{rel} 不存在")
        txt = open(p, encoding="utf-8").read()
        hit = needle in txt
        ok = hit if must else not hit
        return self.check(name, ok, f"{rel} {'含' if hit else '不含'} {needle!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    c = Checker()

    # --- 产物存在性 ---
    for rel in (PLAN, BASE, RULES_STAT, RULES_HOLD, "eval/rules/attribute.py", RESULTS, LOG):
        c.file_exists(rel, rel)
    # held-out 属 P2 待办：当前"未建"是正确状态，建成后才要求 manifest → 不把待办误判为红
    c.check(
        "held-out 状态正确（未建=P2待办 / 已建=含 manifest）",
        (not os.path.exists(os.path.join(ROOT, "evals/heldout")))
        or os.path.exists(os.path.join(ROOT, "evals/heldout/v1/manifest.json")),
        "evals/heldout",
    )

    # --- 48 套件口径（排除 .venv-eval）---
    evals = os.path.join(ROOT, "evals")
    if os.path.isdir(evals):
        # 排除项：.venv-eval（依赖环境）、heldout（P2 隔离集）、
        # rule_redline_v1（P3 红线集）、results（评测运行输出目录）
        # → 这四个都不是"域内能力套件"，计数口径见计划 §18.2 第 1 点
        _EXCLUDE_SUITES = {".venv-eval", "heldout", "rule_redline_v1", "results"}
        suites = [
            d for d in os.listdir(evals)
            if os.path.isdir(os.path.join(evals, d)) and d not in _EXCLUDE_SUITES
        ]
        c.check("evals/ 域内套件数 = 48（排除 .venv-eval/heldout/rule_redline_v1/results）", len(suites) == 48, f"实际 {len(suites)}")
    else:
        c.check("evals/ 目录存在", False, "缺失")

    # --- scenarios_v1.json = 7 场景 × samples 字段 ---
    sp = os.path.join(ROOT, "tests/eval_sets/scenarios_v1.json")
    if os.path.exists(sp):
        try:
            sc = json.load(open(sp, encoding="utf-8"))
            items = sc if isinstance(sc, list) else sc.get("scenarios", [])
            samples_ok = all(s.get("samples") == 6 for s in items) if items else False
            c.check("scenarios_v1.json = 7 场景", len(items) == 7, f"实际 {len(items)}")
            c.check("scenarios_v1.json 样本数字段为 samples=6", samples_ok, "")
        except Exception as e:  # noqa: BLE001
            c.check("scenarios_v1.json 可解析", False, str(e))
    else:
        c.check("scenarios_v1.json 存在", False, "缺失")

    # --- scenarios_v2.json = 14 场景 × samples=6，规则覆盖 ≥12 条 ---
    sp2 = os.path.join(ROOT, "tests/eval_sets/scenarios_v2.json")
    if os.path.exists(sp2):
        try:
            v2 = json.load(open(sp2, encoding="utf-8"))
            items2 = v2.get("scenarios", [])
            c.check("scenarios_v2.json = 14 场景", len(items2) == 14, f"实际 {len(items2)}")
            c.check("scenarios_v2.json 每场景 samples=6",
                    all(s.get("samples") == 6 for s in items2),
                    str([(s.get("id"), s.get("samples")) for s in items2 if s.get("samples") != 6]))
            c.check("scenarios_v2.json 规则覆盖 ≥12 条",
                    len(v2.get("rules_covered", [])) >= 12, str(v2.get("rules_covered")))
            c.check("scenarios_v2.json 总样本 = 84",
                    sum(s.get("samples", 0) for s in items2) == 84, "")
            c.check("scenarios_v2.json verdict 词表覆盖全部场景",
                    all(s.get("verdict") in v2.get("_doc", {}).get("verdict_vocabulary", {})
                        for s in items2),
                    str([s.get("verdict") for s in items2
                         if s.get("verdict") not in v2.get("_doc", {}).get("verdict_vocabulary", {})]))
        except Exception as e:  # noqa: BLE001
            c.check("scenarios_v2.json 可解析", False, str(e))
    else:
        c.check("scenarios_v2.json 存在", False, "缺失")

    # --- 域内快照基线（可复算）---
    bp = os.path.join(ROOT, "evals/BASELINE-20261023.json")
    if os.path.exists(bp):
        import subprocess as _sp
        r = _sp.run(
            [sys.executable, os.path.join(ROOT, "eval/rules/domain_baseline.py"),
             "--verify", "evals/BASELINE-20261023.json"],
            capture_output=True, text=True, cwd=ROOT,
        )
        c.check("域内基线 sha256 全部可复算（domain_baseline --verify exit 0）",
                r.returncode == 0, r.stdout[-300:] if r.returncode else "")
        bb = json.load(open(bp, encoding="utf-8"))
        c.check("域内基线覆盖 48 套件",
                bb.get("summary", {}).get("n_suites") == 48,
                str(bb.get("summary", {}).get("n_suites")))
        c.check("域内基线 schema 正确",
                bb.get("schema") == "lfl-domain-eval-baseline/v0.1", str(bb.get("schema")))
    else:
        c.check("域内基线存在", False, "缺失")

    # --- 治理红线集（P3）---
    _rl = os.path.join(ROOT, "evals/rule_redline_v1/run_redline.py")
    _rl_idx = os.path.join(ROOT, "evals/rule_redline_v1/cases_index.json")
    if os.path.exists(_rl) and os.path.exists(_rl_idx):
        import subprocess as _sp3
        r3 = _sp3.run(
            [sys.executable, _rl, "--selfcheck"],
            capture_output=True, text=True, cwd=ROOT,
        )
        c.check(
            "治理红线集自检通过（≥18 例/六类各≥3/谓词已注册/文件齐备）",
            r3.returncode == 0,
            (r3.stdout or r3.stderr)[-300:],
        )
        _cases = json.load(open(_rl_idx, encoding="utf-8"))
        _cats: dict[str, int] = {}
        for _c in _cases:
            _cats[_c["category"]] = _cats.get(_c["category"], 0) + 1
        c.check("红线用例数 ≥ 18", len(_cases) >= 18, str(len(_cases)))
        c.check(
            "红线六类各 ≥3 例",
            len(_cats) == 6 and all(v >= 3 for v in _cats.values()),
            str(_cats),
        )
    else:
        c.check("治理红线集存在（run_redline.py + cases_index.json）", False, "缺失")

    # --- held-out v1 隔离（P2/D-3）---
    _ho_manifest = os.path.join(ROOT, "evals/heldout/v1/manifest.json")
    _ho_filter = os.path.join(ROOT, "evals/heldout/v1/filter.py")
    if os.path.exists(_ho_manifest) and os.path.exists(_ho_filter):
        import subprocess as _sp2
        r2 = _sp2.run(
            [sys.executable, _ho_filter, "--selfcheck"],
            capture_output=True, text=True, cwd=ROOT,
        )
        c.check(
            "held-out 过滤器自检通过（sha256 齐备/泄漏可抓/正常文本放行/无规则重叠）",
            r2.returncode == 0,
            (r2.stdout or r2.stderr)[-300:],
        )
        _man = json.load(open(_ho_manifest, encoding="utf-8"))
        c.check("held-out 题量 = 23", _man.get("n_tasks") == 23, str(_man.get("n_tasks")))
        c.check("held-out 总样本 = 138", _man.get("total_samples") == 138, str(_man.get("total_samples")))
        _ex = _man.get("exclusion", {})
        c.check(
            "held-out 排除清单含 task_id 与题面 sha256",
            len(_ex.get("forbidden_task_ids", [])) == 23
            and len(_ex.get("forbidden_statement_sha256", [])) == 23,
            "",
        )
        c.check(
            "held-out 排除清单覆盖 method/experience/lesson/memory 载体",
            set(_ex.get("record_kinds", []))
            >= {"method", "experience", "lesson", "memory"},
            str(_ex.get("record_kinds")),
        )
    else:
        c.check("held-out v1 存在（manifest + filter）", False, "缺失")

    # --- 评测执行环境与被测代码来源一致性（known-red §13）---
    # 断言：评测进程实际加载的 llm_loop 源码路径 == 工作树 src。
    # 若 PYTHONPATH 指向 .releases 快照，本地代码改动静默失效（恒 0/1，无报错）。
    try:
        import llm_loop.eval.verdicts as _v

        _loaded = os.path.realpath(_v.__file__)
        _expected = os.path.realpath(
            os.path.join(ROOT, "src", "llm_loop", "eval", "verdicts.py")
        )
        c.check(
            "评测加载的是工作树源码（非 .releases 快照）",
            _loaded == _expected,
            f"实际 {_loaded}",
        )
        c.check(
            "加载的 verdicts 含全部已注册谓词（快照会缺新增谓词）",
            len(_v.VERDICTS) >= 13,
            f"VERDICTS={len(_v.VERDICTS)}",
        )
    except Exception as e:  # noqa: BLE001
        c.check("可 import llm_loop.eval.verdicts", False, str(e))

    # --- 统一统计层 ---
    vp = os.path.join(ROOT, "src/llm_loop/eval/verdicts.py")
    if os.path.exists(vp):
        vt = open(vp, encoding="utf-8").read()
        c.check("verdicts.py 含 wilson_ci", "def wilson_ci" in vt, "")
        preds = sorted(set(re.findall(r"def (verdict_\w+)", vt)))
        c.check("verdicts.py verdict_* 谓词 ≥6", len(preds) >= 6, f"{len(preds)}: {preds}")
    else:
        c.check("verdicts.py 存在", False, "缺失")

    # --- 基线数字：直接复算 results.json ---
    if os.path.exists(os.path.join(ROOT, RESULTS)):
        res = json.load(open(os.path.join(ROOT, RESULTS), encoding="utf-8"))["results"]
        n = len(res)
        nres = sum(1 for r in res if r.get("is_resolved"))
        fm = Counter(r.get("failure_mode") for r in res)
        c.check("基线判定数 = 79", n == 79, f"实际 {n}")
        c.check("基线 resolved = 7", nres == 7, f"实际 {nres}")
        c.check("failure_mode unknown_agent_error = 52", fm["unknown_agent_error"] == 52,
                f"实际 {fm['unknown_agent_error']}")
        c.check("failure_mode test_timeout = 9", fm["test_timeout"] == 9, f"实际 {fm['test_timeout']}")
        c.check("failure_mode unset = 8", fm["unset"] == 8, f"实际 {fm['unset']}")
        c.check("failure_mode parse_error = 5", fm["parse_error"] == 5, f"实际 {fm['parse_error']}")
        c.check("failure_mode agent_timeout = 5", fm["agent_timeout"] == 5,
                f"实际 {fm['agent_timeout']}")
        c.check("failure_mode 分布合计 = 79", sum(fm.values()) == 79, f"实际 {sum(fm.values())}")
        # 口径陷阱：resolved 任务也带 failure_mode
        res_fm = [r.get("failure_mode") for r in res if r.get("is_resolved")]
        c.check("口径陷阱：resolved 任务也带 failure_mode（非空）",
                all(f is not None for f in res_fm), f"{len(res_fm)} 例 resolved")
        # token 稀疏：必须区分 null / 0 / nonzero（独立审查 P1-1 修正）
        def tri(v):
            return "null" if v is None else ("zero" if v == 0 else "nonzero")
        tin = Counter(tri(r.get("total_input_tokens")) for r in res)
        tout = Counter(tri(r.get("total_output_tokens")) for r in res)
        c.check("token 三分: input nonzero=18", tin["nonzero"] == 18, str(dict(tin)))
        c.check("token 三分: input null=52", tin["null"] == 52, str(dict(tin)))
        c.check("token 三分: input zero=9", tin["zero"] == 9, str(dict(tin)))
        c.check("token 三分: output 与 input 同分布", dict(tout) == dict(tin), str(dict(tout)))
        # 52 例 unknown 的 token 字段应为 null（非 0）
        unk = [r for r in res if r.get("failure_mode") == "unknown_agent_error"]
        c.check("52 例 unknown 的 total_input_tokens 全为 null",
                all(r.get("total_input_tokens") is None for r in unk), "")
        c.check("52 例 unknown 的 started_at 全为 null",
                all(r.get("started_at") is None for r in unk), "")
        # 模型来源：run_metadata 的 model_name（独立审查 P2-1 修正）
        mp = os.path.join(ROOT, "eval/results/baseline_v0_terminus2_glm53_full/2026-10-14__20-23-44/run_metadata.json")
        if os.path.exists(mp):
            md = json.load(open(mp, encoding="utf-8"))
            c.check("run_metadata.model_name = openai/glm-5.3",
                    md.get("model_name") == "openai/glm-5.3", str(md.get("model_name")))
            c.check("run_metadata.agent_name = terminus-2",
                    md.get("agent_name") == "terminus-2", str(md.get("agent_name")))
            c.check("run_metadata.dataset_version = 0.1.1",
                    md.get("dataset_version") == "0.1.1", str(md.get("dataset_version")))
            c.check("run_metadata.task_ids 数 = 80", len(md.get("task_ids", [])) == 80,
                    str(len(md.get("task_ids", []))))
        else:
            c.check("run_metadata.json 存在", False, "缺失")

    # --- 归因器可复算（交叉验证子代理/人工复算）---
    script = os.path.join(ROOT, "eval/rules/attribute.py")
    if os.path.exists(script):
        p = subprocess.run(
            [sys.executable, script, "--run-dir",
             "eval/results/baseline_v0_terminus2_glm53_full/2026-10-14__20-23-44",
             "--log", LOG, "--json"],
            capture_output=True, text=True, cwd=ROOT,
        )
        if p.returncode == 0:
            out = json.loads(p.stdout)
            c.check("归因: n_results = 79", out["n_results"] == 79, str(out["n_results"]))
            c.check("归因: 环境类失败 = 52", out["n_infra_failures"] == 52,
                    str(out["n_infra_failures"]))
            c.check("归因: agent 可比集 = 27", out["n_agent_comparable"] == 27,
                    str(out["n_agent_comparable"]))
            c.check("归因: 原口径 = 8.86%", abs(out["raw_accuracy"] - 7 / 79) < 1e-9, "")
            c.check("归因: 可比集口径 = 25.93%",
                    abs(out["agent_comparable_accuracy"] - 7 / 27) < 1e-9, "")
            c.check("归因: 环境占比 = 72.2%",
                    abs(out["infra_share_of_failures"] - 52 / 72) < 1e-9, "")
            c.check("归因: A=27 / B=16 / C=9",
                    len(out["groups"].get("A_docker_build", [])) == 27
                    and len(out["groups"].get("B_errno24", [])) == 16
                    and len(out["groups"].get("C_llm_api_5xx", [])) == 9, "")
            # 稳健性：剔除残差归因 C 组后仍 > 30%（独立审查建议）
            rb = out.get("robustness", {})
            c.check("稳健性: 剔除 C 组后环境侧 = 43/72 = 59.7%",
                    rb.get("n_infra_excluding_C") == 43
                    and abs(rb.get("share_excluding_C", 0) - 43 / 72) < 1e-9, str(rb))
        else:
            c.check("归因器可执行", False, p.stderr[-200:])

    # --- 日志精确计数（独立审查 P0-2 / P2-2 修正）---
    if os.path.exists(os.path.join(ROOT, LOG)):
        lg = open(os.path.join(ROOT, LOG), encoding="utf-8", errors="replace").read()
        n_5xx = len(re.findall(r"Unknown Error in LLM interaction", lg))
        c.check("日志 5xx 错误块 = 30（非 95；95 是 'If you need to debug' 计数）",
                n_5xx == 30, f"实际 {n_5xx}")
        n_em = set(re.findall(
            r"Harness execution failed for \S*/([A-Za-z0-9._-]+): \[Errno 24\]", lg))
        c.check("日志 errno24 distinct = 17（归因 16 + path-tracing 无判定）",
                len(n_em) == 17, f"实际 {len(n_em)}")
        n_bf = set(re.findall(
            r"Harness execution failed for \S*/([A-Za-z0-9._-]+): Command '\['docker'", lg))
        c.check("日志 docker build distinct = 27", len(n_bf) == 27, f"实际 {len(n_bf)}")
        if os.path.exists(os.path.join(ROOT, RESULTS)):
            res_ids = {r["task_id"] for r in json.load(
                open(os.path.join(ROOT, RESULTS), encoding="utf-8"))["results"]}
            c.check("errno24 中 path-tracing 不在 results.json（无判定）",
                    "path-tracing" in n_em and "path-tracing" not in res_ids, "")

    # --- Wilson CI 实算值（独立审查 P1-3 修正）---
    sys.path.insert(0, os.path.join(ROOT, "src"))
    try:
        from llm_loop.eval.verdicts import wilson_ci
        lo, hi = wilson_ci(7, 27)
        c.check("wilson_ci(7,27) = 13.2%–44.7%",
                abs(lo - 0.1317) < 5e-4 and abs(hi - 0.4468) < 5e-4, f"({lo:.4f}, {hi:.4f})")
        lo2, hi2 = wilson_ci(7, 79)
        c.check("wilson_ci(7,79) = 4.4%–17.2%",
                abs(lo2 - 0.0436) < 5e-4 and abs(hi2 - 0.1718) < 5e-4, f"({lo2:.4f}, {hi2:.4f})")
    except Exception as e:  # noqa: BLE001
        c.check("wilson_ci 可导入", False, str(e))

    # --- 文档数字一致性（跨文档）---
    c.text_in("计划含 7/79 = 8.86%", PLAN, "8.86%")
    c.text_in("基线含 7/27 = 25.93%", BASE, "25.93%")
    c.text_in("known-reds 含 72.2%", REDS, "72.2%")
    c.text_in("计划已清除旧口径 68% 说法", PLAN, "68% 的失败是未归因", must=False)
    c.text_in("计划含 D-2 测试模型 M3.1-Flash", PLAN, "MiniMax-M3.1-Flash")
    c.text_in("基线含重跑前置条件", BASE, "重跑前置条件")
    c.text_in("holdout 规则含索引排除清单", RULES_HOLD, "索引排除清单")
    c.text_in("统计卡含 D6 纪律", RULES_STAT, "失败归因先于分数")

    # --- 回归断言：独立审查否决过的表述不得复现 ---
    # 说明：只对"事实性表述"生效；计划 §17 的审查记录中**引用**被否决的原说法属正当留痕，
    #       故对 PLAN 采用"排除 §17 审查记录段落后再匹配"的策略。
    def body_without_audit_record(rel: str) -> str:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            return ""
        t = open(p, encoding="utf-8").read()
        i = t.find("## 17. 独立审查记录")
        return t[:i] if i != -1 else t

    for rel in (BASE, RULES_STAT, REDS):
        c.text_in(f"[回归] {rel} 不再出现 '95 次'", rel, "95 次", must=False)
        c.text_in(f"[回归] {rel} 不再出现 '13%–43%'", rel, "13%–43%", must=False)
        c.text_in(f"[回归] {rel} 不再出现 '全为 0'（应为 null）", rel, "全为 0", must=False)
    for needle in ("95 次", "13%–43%", "全为 0"):
        c.check(
            f"[回归] 计划正文（§17 审查记录除外）不再出现 {needle!r}",
            needle not in body_without_audit_record(PLAN),
            "仅允许出现在 §17 独立审查记录的历史引用中",
        )
    # 计划必须使用实算 CI 值
    c.text_in("计划含 wilson_ci(7,27) 实算值 13.2%–44.7%", PLAN, "13.2%–44.7%")
    c.text_in("known-reds 含 wilson_ci(7,27) 实算值", REDS, "13.2%–44.7%")
    # C 组必须显式标注为残差归因
    c.text_in("基线标注 C 组为残差归因", BASE, "残差归因")
    c.text_in("计划标注 C 组为残差归因", PLAN, "残差归因")
    c.text_in("known-reds 标注 C 组为残差归因", REDS, "残差归因")
    # 稳健性论证必须写进三份文档
    for rel in (PLAN, BASE, REDS):
        c.text_in(f"{rel} 含剔除 C 组的稳健性论证", rel, "59.7%")
    # 独立审查记录必须在计划中留痕
    c.text_in("计划含独立审查回执 REVISE", PLAN, "VERDICT: REVISE")
    c.text_in("计划含未获独立验证项的登记", PLAN, "未能独立确认")

    # --- 汇总 ---
    n_fail = sum(1 for _, st, _ in c.rows if st == "FAIL")
    if args.json:
        print(json.dumps(
            {"total": len(c.rows), "fail": n_fail,
             "rows": [{"name": n, "status": s, "detail": d} for n, s, d in c.rows]},
            ensure_ascii=False, indent=2))
    else:
        for n, s, d in c.rows:
            print(f"[{s}] {n}" + (f"  ({d})" if d and s == "FAIL" else ""))
        print()
        print(f"合计 {len(c.rows)} 项，FAIL {n_fail} 项")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
