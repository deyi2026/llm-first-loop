---
title: 审查门禁的材料上限应按资产类别分级 + 有界投影，而非全局放宽
scenario: "在 llm-first-loop 仓为 vendored 第三方技能（skills/ui-ux-pro-max，49 文件 / 3,330,378B，其中三个文件 823,933B / 747,241B / 433,127B）申请独立审查时，review_admission 连续拒绝：先 review_untracked_file_too_large（单文件 > 200_000B），再 review_untracked_file_limit（untracked 文件数 >= 40），再 git_state_too_large:material_diff>400000。结果是「能 commit、不能 push、永远无法被审查」——门禁与资产形态结构性互斥。"
root_cause: 审查材料的取数上限（400_000B/路径）是为「手写代码 diff」这一形态定的，而 vendored 第三方资产是「整棵数据树」，两者形态不同却共用同一个上限。单纯把 400_000B 调大会撑爆 reviewer 上下文（reviewer=glm/glm-5.3，材料受 registry 上下文预算动态把关，静态上限 2_500_000 字符），所以「只放大上限」不是可行解；真正缺的是「按类别分级 + 投影后送审」这一层。
solution: 按三条并行改造：(1) 引入代码内硬编码的 vendored 资产类别 _VENDORED_ASSET_PREFIXES（放在代码里而非 AI 可写的数据文件，否则门禁可自我授权放宽），类别内 acquisition 上限提到 8MB，类别外保持 400_000B 不变；(2) 类别内超 48_000B 的路径按 head/tail 投影，投影标记显式写明「省略了多少字节、哪条路径」，让审查者知道它没看到什么，而不是给它一份安静摘要；(3) 投影条目数设上限（200），材料总量仍由既有 2.5MB 总上限兜底。untracked 侧对类别内单独计数（400 文件 / 单文件 1MB），与普通路径的 40 文件 / 200KB 完全分开计数，敏感路径拒绝不豁免。冻结头新增 vendored_asset_prefixes 与 vendored_projected_entries 两个字段，使审查材料本身记录「哪些路径被放宽过」。当前性验证：cd /Users/<user>/Project/llm-first-loop-mirror && .venv/bin/python -m pytest tests/unit/test_review_host_admission.py -k vendored -q 应得 10 passed；.venv/bin/python -m pytest tests/unit/test_review_host_admission.py -q 应得 166 passed。
evidence: "端到端实测（evidence://v1/e63271f6f43cab645f9b048b29fd500c86ef4f07d403617ff792ee82a306a294）：真实 3.3MB skills/ui-ux-pro-max 复制进 scratch git 仓提交后，vendored 类被放行，材料 1,286,732B（< 2.5MB 上限）、含 10 处投影标记、冻结头含 vendored_asset_prefixes；对照组把同一目录放在非 vendored 路径仍被拒，理由 git_state_too_large:material_diff>400000 且 reviewer 从未启动（双向实测，RULE-AI-35 要求）。回归：tests/unit/test_review_host_admission.py 166 passed（含新增 10 个，evidence://v1/9c7819d67191ba84a601aca8b94af8405c2663befa48e25fe2ffe9a8c066c58c）。"
tags: [review-admission, guardrail, vendored, projection, rule-ai-35, skills]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T20:25:42.332926+08:00"
updated_at: "2026-10-31T20:25:42.332926+08:00"
---