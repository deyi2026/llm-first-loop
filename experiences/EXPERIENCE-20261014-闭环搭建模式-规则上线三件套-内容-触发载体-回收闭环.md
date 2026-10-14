---
title: 闭环搭建模式：规则上线三件套（内容+触发载体+回收闭环）
scenario: 规则/机制/配置上线时只落地内容文字，不留触发载体与回收闭环，导致规则落灰。实证（2026-10-14 盘点）：INBOX_WAKEUP=1 自 2026-08-18 重开约 8 周无任何验证/回收记录（.env 中「验证计划/回收条件」注释 0 命中）；tool-stability.md 的 SoT 计数（RULE-AI-00..30）在规则 31/32 落地同日即漂移；ai_rules.en.md 与中文 SoT 脱节且自称 SoT、无测试守护。
root_cause: ""
solution: 规则上线三件套，缺一即落灰：①内容——SoT 文字，硬编码计数带「截至日期」；②触发载体——班次/同步测试/durable task 验收/审查闸，纯靠模型想起的规则低频必失效；③回收闭环——临时配置上线即写验证计划+回收条件并挂 task 验收；历史设计段落保留时加现状注记；跨语言副本要么声明 stale snapshot 要么纳入同步测试。当前性验证动作见 body 末行（grep 探针）。
evidence: "三处修改回执：en.md artifact://v1/d6ddd1cd7a894be9b0c119c56c3de6e8；tool-stability.md artifact://v1/a27ade3d40864b688be683d37bce08e9；ARCHITECTURE 注记 artifact://v1/659a392838d244ea8eb9c0dba97abc0f（均为 2026-10-14 写后复读一致回执）"
tags: [闭环设计, 文档治理, 规则生命周期, 配置治理]
source: {}
status: active
record_kind: lesson
verification_state: unverified
created_at: "2026-10-14T12:56:43.276097+08:00"
updated_at: "2026-10-14T12:56:43.276097+08:00"
---

三件套缺一即落灰。①内容：规则正文进 SoT，硬编码计数（规则条数/行数）一律带「截至日期」范围表述，否则下次演进必漂移（反例：tool-stability.md 写 00..30，规则 31/32 落地当天即少计）。②触发载体：明确谁在何时被触发——班次（如 card-lifecycle 挂晚班）、同步测试、durable task 验收标准（如涉代码/push/文章任务在 task_create 验收中写明三闸回执 ref，复用 evidence_required 机制）、或检索面（RULE 卡可水合）。触发载体纯靠「模型想起」的规则，低频必然失效。③回收闭环：临时配置/开关/机制上线时写明验证计划与回收条件，挂到对应 task 验收；文档中的历史设计段落保留时必须加「现状注记」指明现状与迁移去向，跨语言副本（en.md 类）要么声明 stale snapshot 指向主 SoT，要么纳入同步测试，不留无人认领的中间态。
当前性验证：grep -n "STALE SNAPSHOT" docs/ai_rules.en.md 应命中头部注记；grep -n "00..32" docs/governance/tool-stability.md 应命中规则条目行；grep -c "验证计划" .env 为本卡反例是否仍存在的探针（0 且 INBOX_WAKEUP 仍在 ⇒ 反例未收口，对应 TASK-46b9600a-001）。