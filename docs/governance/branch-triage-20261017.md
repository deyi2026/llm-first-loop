# 存量分支显式归类（branch triage）

- 日期：2026-10-17
- 授权：用户指示"解决存量实验分支（如 SoT 里登记的 P0-B'尚未合并 main'）显式归类：要么过闸合并、要么留痕'长期实验不合并'"
- 依据：RULE-AI-34（分支收口合并闸，2026-10-17 生效，commit b184edf9c）
- 基准：main @ b184edf9c7ecc16014c1806fd1c0bedff7a440cb（归类时点 HEAD，b184 线合并前）
- 范围：本地分支 106 个；其中 28 个 NOT-IN-MAIN（`git merge-base --is-ancestor` 判定）
- 方法：is-ancestor 机械分类 → ahead 提交 cherry/两点 diff → 关键符号/文件在 main 的存在性核验。证据强度分级：【铁证】符号级核验；【链证】提交信息+收敛分支 IN-MAIN；【判证】系列演化推断，未逐提交核验

## A. 本轮过闸合并（1）

| 分支 | ahead | 归类 | 证据 |
|---|---|---|---|
| integrate/web-multiagent-host-b184-20261017 | 2 | **过 merge-review-gate 后合并** | merge-base=b184edf9c（=归类时 main HEAD，可 ff）；8784c28cc（src+tests 15 files +1464/-22，自带独立 GLM-5.3 审查 PASS P0=0 P1=0 P2=4，冻结树 SHA 962d37601c93…）+ 0bf209354（docs 收口回执，R9 exit 0 全量 9201 passed/141 skipped/0 failed）；worktree 树干净。gate 回执：docs/governance/receipts/merge-gate-web-multiagent-b184-20261017.json |

## B. 已被取代，留痕不合并（14）

内容已经后续演进/收敛链路实际进入 main，原始分支为历史现场，按卫生契约可后续删除（本次不删）。

| 分支 | 被什么取代 | 强度 |
|---|---|---|
| feat/knowledge-consumption-receipts-20260909 | provider_settlement.py / test_knowledge_consumption_receipts.py 等以演进版在 main 存在；后续 knowledge 系列（knowledge-consumption-main-20261010 等）IN-MAIN | 铁证 |
| fix/rule-boundary-agency-20261014 | search_records "每类≤5" 描述、rule_index._SECTION_HEADING_RE 均已在 main；分支两点 diff 显示其整体落后 main（无 review_authorizer 等） | 铁证 |
| fix/rule28-host-admission-20261015 | **P0-B 原始现场**。HostReviewAdmission/review_admission 由 604592a24（reconcile 链）引入并存在于当前 main；SoT ai_rules.md:463 登记已同步修正 | 铁证 |
| fix/rule28-p0c-current-main-20261015 | P0-C 集成现场，经后续收敛链进 main（fix/rule28-jev-converged-20261015 IN-MAIN） | 链证 |
| fix/rule28-main-gates-20261015 | 同上收敛链 | 链证 |
| fix/rule28-main-c8e50-joint-20261015 | c8e50 联审线，经 fix/rule31-main-c8e50-admission-20261016 IN-MAIN 收敛 | 链证 |
| fix/rule31-current-main-20261015 | rule31 系列由 16 日版整合分支（IN-MAIN）演进收敛 | 判证 |
| fix/rule31-current-main-integration-20261015 | 同上 | 判证 |
| fix/rule31-jev-main-c8e50-20261015 | 同上 | 判证 |
| fix/rule31-main-integration-20261015 (HEAD=2ad0bc06d) | 16 日版 IN-MAIN 演进取代；其 review-prerequisite 增量被 f-batch 线挑入 | 链证 |
| fix/subagent-lifecycle-audit-20261016 | `git cherry main` 输出 `-`：补丁等价物已在 main（fix/subagent-lifecycle-main-integration-20261016 IN-MAIN） | 铁证 |
| fix/web-multiagent-canary-host-20261016 | 被 b184 线 8784c28cc 重基+交叉加固取代 | 链证 |
| fix/web-multiagent-canary-main-integration-20261016 | 同上 | 链证 |
| fix/web-multiagent-host-main-20261016-current | 8041dc357 基线旧代，被 b184 重基取代 | 链证 |

## C. F 批整合簇，待补闸（11）

**合规缺口披露**：main 上 596bad1b8"处置报告追加 F 批执行结果（集成分支 9 commits、测试 82+29+29 passed）"已报告执行，但 `merge/f-batch-20261017`（17 个非 merge 提交未落地）与 `integrate/f-batch-v2-20261017`（4 个 docs 提交未落地）均 NOT in main——RULE-AI-34 前时代"报告收口、代码未进 main"实例。处置：登记为最高优先补闸待办，整合时逐项过 merge-review-gate；不机械合并。

| 分支 | 内容 | 备注 |
|---|---|---|
| merge/f-batch-20261017 | 17 非合并提交：method telemetry 修复、provider spec 测试同步、jev pyright（c0f577d18）、canary 系列合并、learning 六分支合入 | 主整合线 |
| integrate/f-batch-v2-20261017 | 4 docs 提交：GLM review/R9 回执归档 | 与上互有独有提交（23/7） |
| fix/learning-source-deleted-{02c7,597,af4,c240,c72a,ea1d}-*（6 个） | learning 处置线；c240/c72a 部分经短名分支 IN-MAIN，整体在 f-batch 线 | 随 F 批收口 |
| fix/jev-wire-pyright-narrowing-20261015 | c0f577d18 已在 f-batch 线 | 随 F 批 |
| fix/review-prerequisite-20261015 | 2ad0bc06d 基线增量，被 f-batch 精准挑入 | 随 F 批 |
| fix/architecture-guard-and-agency-20261014 | 测试部分已被 f-batch 提取（ed3248d60）；**src 部分与 main 现行演进冲突方向未定**（ed3248d60 原话） | 整合时一并裁决 |

## D. 长期实验不合并（2）

| 分支 | 理由 |
|---|---|
| feat/harmonyos-native-agent-poc-20261011 | 鸿蒙原生 A2A PoC（59 files +3333），独立 SDK 实验线，非 main 演进路径；保留为实验现场 |
| chore/harness-evidence-20261006 | eval 证据归档线（172 files +27433），证据性质而非产品代码 |

## P0-B SoT 登记修正（同日完成）

ai_rules.md:463 原"P0-B（2026-10-15 独立实验分支，**尚未合并 main、尚未部署**）"为**陈旧登记**：代码经 604592a24 起的收敛链实际并入 main 且随部署生效（当前运行时存在 review_admission 工具），原始实验提交 7e4efb3dd 未直接合并。已改为事实准确表述并指向本文档。

## 后续动作

1. b184 线 gate PASS 后 ff 并入 main（本次执行，见 A 组回执）
2. F 批整合簇补闸：先裁决 architecture-guard src 取向 → 单线整合 merge/f-batch + f-batch-v2 → merge-review-gate → 并入 main（待办，未排期）
3. B/D 组分支保留为历史现场；批量删除属卫生契约动作，待用户明示后执行
