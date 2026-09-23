---
method_id: adversarial-cross-review-before-high-stakes-output-8a3f221d3646
name: adversarial-cross-review-before-high-stakes-output
description: 架构改动、安全边界、对外正式结论类产出，在输出前用 2-3 个独立子代理（spawn_subagent）从对抗立场互审：各自找反例与边界失效条件而非背书；冲突点由主模型显式裁决并记录；每个关键 claim 标注 verified（≥2 独立来源/视角交叉确认）/ unverified（单源）。机械任务与低风险产出不启用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:87:2e978f37312a9c6b95b0
evidence_refs: method:self-execute-review-contract-on-degenerate-tool-output-c1088a737f27
created_at: 2026-09-23T12:26:00.749588+00:00
updated_at: 2026-09-23T12:26:00.749588+00:00
---
触发条件：产出属于架构改动、安全/授权边界、对外正式结论、跨系统接口契约等高影响类别，且具备可并行审查的独立视角。流程：1) spawn 2-3 个独立子代理，各自任务书明确"找反例、找边界失效条件"，禁止背书式评审；2) 主模型收齐后逐冲突点显式裁决，裁决理由随结论记录；3) 关键 claim 逐一标 verified（≥2 独立来源/视角交叉确认）或 unverified（单源），未验证不伪装成已验证；4) 评审视角不足或子代理输出退化（壳结构完整但零实际问题）时，按既有方法卡 self-execute-review-contract-on-degenerate-tool-output（candidate，2026-09-23 已补首次执行 use 记录，未经独立 qualification）处理：按声明的评审领域自问自答补齐，不做无限重试。成本约束：机械任务、低风险产出、纯事实查询不启用；并行度默认 ≤3，扩大需写明理由。来源：Claude Code workflow 官方文档的 adversarial review 模式 + deep-research 的 claim 级交叉验证与 unverified 标注（2026-09-23 抓取），与本地 grill_me 退化输出教训合并。验证状态：未在本工作区独立验证效果，candidate。
