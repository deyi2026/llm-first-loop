---
method_id: r9-gate-breakdown-triage-47132c4c89f8
name: r9-gate-breakdown-triage
description: r9 提交门禁在合并后 HEAD 反复中止/暴露未知红时的分流诊断：基建失败（探针标记失配/mktemp 沙盒/manifest 漂移）与测试红（我方带入 vs 外部演进链配对面缺口）分离处置
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:2274a444-654d-46a3-a72b-2d83058b2289
created_at: 2026-09-09T20:43:04.949486+00:00
updated_at: 2026-09-09T20:43:04.949486+00:00
---
症状分流树：
1. 「未达 [N/N] 测试步——基建失败」→ 不是测试问题。grep -n "═══ \[" ci_gate.sh 看实际步进标记（可能混合格式如 [1/4]+[x/5]），再 grep 探针脚本（r9_commit.sh）的探测标记，两者失配=探针 bug，对准最终测试步。修后 bash -n 验语法。
2. ci_gate 中途中止无输出 → mktemp 无参模板可能被执行沙盒拒（mktemp: too few arguments）。显式 /tmp/ 前缀模板。GATE_LOG 变量逐层检查。
3. 暴露未知测试红 → (a) 收集精确红集：grep -oE "FAILED [^ ]+" | awk '{print $2}' | sort -u；(b) registry（tests/guards/external_red_registry.json exempt 数组，grep -qF "\"$t\"" 引号定界精确匹配）比对差集=新红；(c) 逐项归因：git merge-base --is-ancestor <红引入提交> <Gate0 重建提交> 为 false 则该红在 Gate0 复核后合入=外部链配对面缺口，登记 registry（exempt 追加 + _meta 最后复核写归因/时点/销号路径），不代修；(d) 我方改动带红 → 修复后重跑，不带豁免。
4. fixture manifest 死哈希漂移 → 源 fixture 变更（此处 death-loop-scenario.json 外部链更新），manifest 同步新 sha256，不"修复" fixture 回旧值。
约束：登记时点必须实测全量红集恰为登记项（防夹带私货——豁免机制只能登外部红，不能登自己想绕过的红）；销号复核沿独立裁决逐批；PROBE 态 registry=提交态随提交原子生效。
