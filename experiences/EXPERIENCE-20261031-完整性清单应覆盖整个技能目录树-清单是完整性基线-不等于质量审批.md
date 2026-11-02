---
title: 完整性清单应覆盖整个技能目录树；清单是完整性基线，不等于质量审批
scenario: 为 llm-first-loop 的 skills/ 目录开完整性门禁（LFL_SKILLS_REQUIRE_MANIFEST）。仓库原有 loader 只对每个技能的 SKILL.md 取 sha256，写入 skills/.manifest.json。若照此开清单，门禁对实际资产形同虚设：SKILL.md 只是指向 scripts/、data/、sections/ 的索引，执行输入是那些文件；「改了脚本、没改 SKILL.md」的变更会完全隐身。
root_cause: 两个混淆叠在一起。其一是覆盖对象错：把「技能的入口文件」当成了「技能的内容」。其二是语义错：清单若被称作「审批」，AI 代跑生成清单就等于伪造人工审阅痕迹——仓库原脚本 approve_skills.py 本就写明「勿交给 AI 代跑，AI 同时可写技能与清单，代跑等于自批」。
solution: 清单升级为 v2：每个条目除 SKILL.md 的 sha256 外，增加整个技能目录树的 tree_sha256 与逐文件 files 映射，判定依据改为 tree_sha256（不一致时指名改了哪个文件），排除项仅 __pycache__/.DS_Store/.pyc 与清单自身。语义上把「完整性」与「质量审批」分开：清单=完整性基线（证明内容与登记时一致），不证明内容被谁逐字读过；approved_by 默认值为 baseline，语义是「脚本按现状生成」，人工复核后须写入具体标识，AI 代跑不得冒充人工签字。门禁四态在 v2 下 fail-closed：缺 tree_sha256 的登记条目按 unlisted 拒绝。纳入范围写明 skills/ 下含 SKILL.md 的一级子目录，标准包技能(pkg/name)不在本门禁管辖——这是已知边界，不得误认为全覆盖。
evidence: "实测 skills/ui-ux-pro-max = 49 文件 / 3,330,378B，SKILL.md 只是其中之一（三个大文件 823,933B/747,241B/433,127B）；本仓 skills/ 共 39 个技能 / 321 文件 / 7,034,122B，目录树哈希成本可接受。回归：tests/test_skills_integrity.py 等 4 个文件 63 passed；新增用例覆盖「改辅助文件 → modified 且指名 run.py」「新增文件 → modified」「vendored 技能记录 upstream」「缺 tree_sha256 → unlisted」。口径文档：docs/skills-integrity-policy.md（含诚实边界：清单与技能同在 AI 可写目录内，本机制是可检测+需过基线，非防篡改强隔离；真正的分界在推送环节的独立审查）。"
tags: [skills, integrity, manifest, guardrail, honesty]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T20:25:35.431508+08:00"
updated_at: "2026-10-31T20:25:35.431508+08:00"
---