---
title: 显式语义经验注入会劣化长程探索：回放事实优于语义总结（Dream-RSI 结论，文献来源）
scenario: "长程发现式任务（算法工程、数学优化、GPU kernel 等）中，harness 把上一轮/历史轨迹抽象成\"方向性经验/教训\"文本并注入下一轮 prompt，用于指导探索策略。"
root_cause: "高层语义先验是对已实现搜索空间的有损压缩；它隐式剪枝未来搜索树。正确单位应是\"结构化事实+可回放的 outcome\"，语义方向只应作为假设而非约束。"
solution: 不要把历史轨迹的语义总结作为 prompt 注入来指导探索；优先回放式评估——让候选策略直接在结构化历史（discovery tree：每个探索决策+其真实执行结果）上重走，零执行成本筛选，只有胜者上线。若确需传递语义知识，显式标注为可推翻假设，保持线程多样性。
evidence: "evidence://v1/af81c208de22c4eb5501776b654559a701fb007bac72f8d408c165e5b1726664 (https://dream-rsi.com 全文，acquired_at 2026-09-19T03:05:41Z，blob_sha256=1fd2e437e222c0510726b13203a06da61dbe943287f50f837ed81958ec9d4744)；arXiv 检索无命中（BibTeX 为占位符 XXXX.XXXXX），论文未公开，无法二次来源交叉验证"
tags: [harness-design, exploration-policy, semantic-compression, dream-rsi, replay-vs-summary]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-19T11:07:10.555775+08:00"
updated_at: "2026-09-19T11:07:10.555775+08:00"
---

来源：Google Dream-RSI 项目页（dream-rsi.com，Technical Report 2026，Zheng Tong 等；论文 arXiv 编号尚为占位符，未公开收录，以下均为项目页单一来源，未在本系统复现）。

发现（页面原文段落 "Semantic guidance is worse than replay"）："A natural alternative is to abstract prior trajectories into high-level directional insights and inject them into the prompt. Applied to both paradigms, this explicit guidance consistently underperforms its unguided counterpart under equal budgets. In long-horizon discovery with many parallel threads, strong semantic priors about where to search over-constrain the space and suppress diverse exploration."

机制解释：在长程、多并行线程的发现式任务里，"哪里值得搜"的高层语义结论是过早收窄的先验；它把当前看似无望、实则可能有价值的分支提前剪掉。而 Dream-RSI 的替代方案是 replay——新策略在历史 discovery tree 上按事实回放重走，只消费已落盘的真实执行结果（每个节点带真实 outcome），不做语义抽象。

对本系统（LFL harness）的迁移规则：
1. 给后续 run 传递历史知识时，优先结构化事实回放（原始决策 + 真实 outcome + 失败现场），而非叙事性"经验总结"注入 prompt；若必须注入，标注为可推翻的假设而非指令。
2. 与既有 lesson（压缩摘要不可替代源事实、会误导下游动作）同机制：有损语义压缩让下游过早收窄搜索/行动空间。
3. 适用边界：文献结论来自长程发现式任务（算法工程/数学优化/GPU kernel）；对短程、目标明确的执行任务，适度经验注入的收益/代价可能不同，不外推。