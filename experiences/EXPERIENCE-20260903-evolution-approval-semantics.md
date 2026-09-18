---
title: 演进审批语义收正：批准的是问题成立而非实现手段——限制类机制需反向证明必要性
scenario: 演进建议审批后的实施阶段：owner 复审发现原建议正文的具体实现手段有问题（或根因误判），需要部分推翻已 accepted 的方案；以及未来任何『限制模型工具调用/限制轮数/自动判定完成/强制收口/自动注入提示/重复 Schema/自动 replay 历史』类机制的立项评审。
root_cause: 原审批把『问题成立』与『正文手段正确』捆绑；且加限制器/注入器类机制的成本（模型自主性受损、prompt 税、双真值源漂移）在批准时点未被对称审视。EVO-20260903-c8f40b65 的根因误判即为例证：把子代理协议配对缺陷（assistant(tool_calls) 声明未持久化 → 下一轮模型看不到自己刚执行过什么 → 重复调用）误诊为『模型不收口』，强制收口治的是症状，还剥夺了模型自主完成判断的权力。
solution: ① 账本收正而非旁注：rejected 直接改 status，原审批历史进 reason_history（含 rejected_reason），正文改写为复审结论——不留两个真值源。② 方案重写原则：机器可读 Schema 是参数约束唯一真值，description 不重复投递（lazy 骨架保留 enum，仅 index-only 无 properties 路径内联紧凑摘要）；诊断/观测数据只存轻量引用（稳定 check_id + 摘要 + tool_call 关联），显式水合才展开，禁止自动进 prompt、禁止充当 blocker/早停器。③ 实施前先验证根因（协议配对缺陷≠模型不收口），治本不治标。④ 通用原则：演进建议批准的是『问题值得解决』，不是正文每个实现手段；限制类机制实施前必须反向证明『为什么必须存在』，证明不了优先删除——不因已写过/测过/曾经 accepted 就保留。
evidence: "data/audit/evolution_suggestions.jsonl（EVO-20260903-c8f40b65 rejected + reason_history 留痕；EVO-20260903-20152277/06e5a2fd 复审修订版 content）；src/llm_loop/tools/registry.py（_lazy_schema_skeleton/index_schemas）；src/llm_loop/feedback/validator.py:313（check_id）；src/llm_loop/introspection/search.py:701-706（精确 eval_id 水合门）；tests/unit/test_subagent.py L69/L99（防强制收口回归测试）；三套测试 79 用例全绿"
tags: [evolution-lifecycle, owner-agency-first, single-source-of-truth, anti-overreach, approval-semantics, prompt-hygiene, EVO-20260903]
source: {}
status: archived
created_at: "2026-09-03T19:45:00+08:00"
updated_at: "2026-09-06T00:06:07.826813+08:00"
promoted_to_rule: RULE-AI-06
---

2026-09-03 owner 复审三件演进建议时确立。判定清单（加机制前自问）：
1. 它解决的是真根因还是症状？
2. 模型自主裁决权是否被程序剥夺？
3. 数据是否只存一份、引用是否轻量可水合？
4. 能否事后证明"没有它也行"？
任何一条答不上来，就先不做。已批准≠已锁定：进一步证据证明某条规则/提示/自动终止器/限制器/注入机制没有必要，直接撤销或修改。

