---
title: "接受门槛的噪声底线：verified 需\"复现≥2 或机制可解释\"二居一，否则降为 unverified"
scenario: "在 save_experience 上标 verification_state=verified、或提交 evolution 提案 / method qualification 判 pass 时，只有一次成功样本支撑。现有配置底线只看样本量，没有\"效应是否超出噪声范围\"的判断。"
root_cause: 生产即评测、无 holdout 可重放：单次成功样本与噪声不可区分；现有程序门槛（method_reflection_min_failures=2 / self_eval_min_samples=5）只约束样本量，不约束效应量。
solution: "落 verified 前强制二问，居一才通过：(1) 复现性——同一机制在 ≥2 个独立场合成功（不同会话/任务类型）；(2) 机制可解释——能说清因果链且能点名排除\"当前会话/环境特例\"。不满足任一 → verification_state=unverified，标注\"单样本，未过噪声底线\"。写 evolution 提案时附一句\"为何这不是会话/环境特例\"。"
evidence: "本会话 architecture_status(knowledge_health) 回执：usage.jsonl 7 条记录全为 applied/adapted、0 rejected，现有账本未承载\"区分机制与噪声\"的判定；RRSI 对照为本会话上游结论。"
tags: [acceptance-gate, noise-floor, verification, evolution, method-qualification, overfitting]
source: {}
status: active
record_kind: lesson
verification_state: unverified
created_at: "2026-10-10T08:47:21.835756+08:00"
updated_at: "2026-10-10T08:47:21.835756+08:00"
---

2026-10-10 与 RRSI（evolution-loop 论文）逐机制对照后确立。适用边界：仅约束"沉淀/晋升"时刻（save_experience 标 verified、evolution 提案、method qualification 判 pass），不约束普通工具使用决策——后者按当下证据正常推进，不受此门拖慢。反例自警：会话特例拟合典型形态是"本会话 tips 注入有效"被写成"tips 注入普遍有效"；环境特例形态是"本地 mlx 环境结论"被当成通用结论。前者靠跨任务复现排除，后者靠"机制解释是否绑定特定环境参数"排除。