# 交付报告：GOAL-20261015-ac085ab1（任务知识使用反馈与检索闭环·最小闭环）

日期：2026-10-16 00:10（宿主本地）｜调度会话：f3bcb24f-1f02-4da7-aaad-75bb446ffa88

## 交付物（对应设计草案 v3 的最小闭环）
- `src/llm_loop/use_ledger.py`（新）：两层键（slot_id/submission_hash）幂等账本原语、supersedes 链校验、行级 integrity 凭据、torn-tail 隔离恢复、legacy 桶分层。
- `src/llm_loop/introspection/settlement.py`（新）：knowledge_read 打点结算、待结算清单、批量提交、结算成本计数；unresolved 归属显式退化（不伪造哨兵）。
- `src/llm_loop/methods/store.py` / `src/llm_loop/experiences/store.py`：record_use 重写（explicit>episode_fallback>unresolved 层级、slot 派生、对象边界去重）。
- `src/llm_loop/factory.py` / `introspection/search.py` / `registry_experience.py` / `tools_status.py`：打点接线、注释投影、零行为回退。
- 测试：`test_use_ledger_contract.py`、`test_settlement_receipts.py`、`test_search_feedback_reflow.py`（+watermark 适配）。
- 守卫登记：`tests/guards/function_size_baseline.json`（use_ledger 顶层单元 + durability 写入候选，guard(r9) 前缀）。
- 提交：c72a615c0（batchB+设计文档+回执）→ 02c7a5382（P1 窄修+pyright 收窄）→ 4df9ac373（登记残留+全量门回执）。

## 质量链（全部真实回执）
1. r0 独立代码审查：REQUEST_CHANGES（P1×3 + P2×10）→ 修复。
2. r1 窄复审：PASS（P1-1/2/3 全 FIXED，指纹登记）。
3. Rule28 Host 准入 r2：PASS（candidate=7ddc0d4e；审出并修复 P1：use_ledger slot='' 去重缺对象边界——跨 ref 相同默认内容折叠串回执；另 7 处 pyright 收窄）。
4. 全量门首跑：319 中 3 守卫红（登记缺口×2 + factory 函数内 import 63→64）→ 登记+import 归位（守卫 30/30 绿）。
5. Rule28 Host 准入 r5：PASS（candidate=3dd5134a，小上下文残留审）。
6. 全量门（scripts/ci_gate.sh 直接调用，workdir=仓库根）：**exit=0 全链路通过**（ruff new=0／env-pin／pyright new=0 历史债 45→16／tier0 319 passed／全量门禁）。
7. 回执落盘：`docs/governance/receipts/20261015-ac085ab1-{code-review,code-review-r1,full-test-gate}.json`。

## 自指验证
收口时 method_use_gate 硬门真实触发并放行（2 条 method record_use 入账，episode_ref 生成）——本 Goal 建设的账本在自己的收口流程中运转。

## 过程异常与处置（复盘用）
- 上一 run 中断：修订代理被连带取消留半成品（测试已加、产品未修）；本轮指纹比对后重派完成。
- stash@{0} `batchB-rest`（22:39:18，上 run 为缩准入材料所为）致 8 文件"失踪"：以 `git show stash@{0}:<path>` 只读提取恢复，3 文件指纹与 r1 回执逐字节一致；stash 条目保留备查。
- 准入 192KB 材料上限：以"提交已审大头、留未审残留"合规瘦身（本地提交不触发推送/全量门）。
- 准入审查 child 连续空响应（LLMEmptyResponseError）：采纳用户假设缩审查上下文（75KB→2.3KB）后一次通过；与 provider 抖动窗口并存，因果保留单例证据。

## 遗留（不阻断，已记账）
- P2×10（r0）+ P2×7（准入审查）待后续批次；settlement 尚未接线工具面（P2-10）。
- `reports/phase*/` 下 M 状态为全量测试自生成报告，未纳入提交。
- stash@{0} 保留（含 2 个与审查基线有版本差的文件快照）。
