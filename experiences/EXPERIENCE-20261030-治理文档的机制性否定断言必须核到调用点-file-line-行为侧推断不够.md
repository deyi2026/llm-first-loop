---
title: "治理文档的机制性否定断言必须核到调用点（file:line），行为侧推断不够"
scenario: "GOAL-20261030-fc31abda：修订 card-lifecycle 批量纪律时，同一会话内连续写错两条背景事实——先写「1569 张卡 usage 账本全空」（实际 88 条/62 卡，查的是每卡目录而非 store 级共享账本），又写「结算回执与 usage 账本是两套互不相通的写入」（实际 settlement.py:775 自 c72a615c≈2026-10-16 起直调 MethodStore.record_use，89 行中 53 行带只有结算通道写入的 run_id/attribution）。两次都是行为侧推断替代了调用点核验，且都被随后调研推翻。"
root_cause: ""
solution: "机制性否定断言（「不通/为空/从未」）落治理文档前，必须在**两侧写入路径的具体调用点**（file:line）核验：1) 找接收方写入 API 的全部调用位置；2) 确认账本/存储的真实物理位置（store 级共享文件 vs 每卡目录），在正确位置数数；3) 生产数据找只有该通道会写的溯源字段做旁证。行为侧观察（「卡都停在 candidate」）只能提示疑点，不能充当拓扑结论。子代理调研结论也要父会话抽查关键 file:line 再改文档。"
evidence: "src/llm_loop/introspection/settlement.py:775/_submit_one 中 store.record_use 直调（父会话 sed 亲核）；git log c72a615c0（goal ac085ab1 batchB 落地，2026-10-16 前后）；data/methods/usage.jsonl 实测 89 行中 53 行带 run_id/attribution；本会话 settlement_submit 2 条后账本 90/91 行（evidence://v1/f63812e2401fe5a54d701f5e2a71e00d11a08fe4a3c0ea1fd9d14f1ea0a05663、evidence://v1/d878d0b926b6c31345fad4e80ddafb15d3ca370097afac5e0d90a38de6663152）；docs/governance/card-lifecycle.md 70 行修正记录（两次修正注记，commit e123a81b2）。"
tags: [治理文档, 事实核验, 机制断言, 调用点, 否定断言, GOAL-20261030-fc31abda]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T09:43:40.324675+08:00"
updated_at: "2026-10-30T09:43:40.324675+08:00"
supersedes: [EXPERIENCE-20261030-method-卡-qualification-通道的断点-写回执能力一直在-断的是回执-lifecy]
---

## 适用信号
要把「X 与 Y 互不相通」「X 从未发生」「某账本是空的」这类**否定式机制断言**写进治理文档/规则时——尤其断言将作为通道设计依据（如「所以要新建桥接」）。

## 不管什么
- 不是「用户断言规则过期」场景——那归 method:adjudicate-governance-staleness-claim-by-line-diff-and-sync-pairing（按行 diff 判内容同一性）。
- 不是「回执写入规则」场景——那归 method:candidate-qualification-channel…-bbe0ef1d21dc（先核 store 侧规则）。
- 本卡管的是：**系统拓扑级否定断言**（有没有通路/有没有发生过），管「查的位置对不对、查到的是不是调用点」，不管断言内容本身的语义判断。

## 核验方法
1. 否定断言先拆成「写入侧调用点」：grep 接收方的写入函数名（如 record_use）在整个 src/ 的调用位置，列出 file:line——有调用点即断言不成立。
2. 「账本为空」类断言先确认账本的真实物理位置（store 级共享文件 vs 每卡目录），再数行数；查错位置会得出假阴性。
3. 生产数据佐证：账本行里找只有该通道会写的字段（如 run_id/attribution），存在即通道活。

## 核验记录
- 2026-10-30：R3-bis 修订连续两次翻案——初版「usage 账本全空」因查了不存在的每卡目录位置；早版「结算与 usage 互不相通」被 settlement.py:775 直调 record_use（c72a615c≈10-16）+ 89 行中 53 行带 run_id/attribution + 本会话结算 2 条当场新增 2 行（91 行）推翻。三次核验均在调用点级完成。