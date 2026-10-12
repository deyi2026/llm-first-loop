---
title: 本地模型 Skill 发现：专业工作流在 shell 探测前先 skill_list
scenario: 本地 Ornith 面对 PDF/格式转换等已有专用 Skill 的任务时，若 compact skill_list 只写“列技能”或抽象“可能命中技能库”，会直接用 execute_command 探测 pandoc/reportlab，自造流程并增加失败概率。
root_cause: 能力没有消失，断点在 Skill discoverability：工具表里有 skill_list/skill_load，但本地模型需要足够具体的任务类触发线索，才能在通用 shell 探测前把专业工作流与 Skill 发现联系起来。
solution: skill_list 的 compact/JIT 契约保留少量代表性任务类（格式转换/PDF、特定站点抓取、运维诊断），并明确“准备自己用 execute_command 探测或拼装流程前先发现候选”；是否加载/采用仍由模型根据当前任务判断。skill_list 命中后再按稳定名称 skill_load，不自动路由、不隐藏其它工具。
evidence: 2026-09-11 同一 Ornith-1.5-35B-A3B-MLX、temperature=0、同工具面单变量回放：较弱 compact 文案 2/2 首调 execute_command；恢复旧完整 skill_list 文案仍 2/2 execute_command；仅换成具体任务类+shell 前发现候选的 tool-local JIT 后 2/2 首调 skill_list。真实 22 项 Skill 清单含 md2pdf 后，第二跳 2/2 精确 skill_load(md2pdf)。负对照“读 pyproject.toml”走 search_files、“git status”走 execute_command，未被 Skill 提示劫持。
tags: [local-model, tool-discovery, skill, pdf, compact-schema, ornith, llm-first]
source:
  kind: failure_replay
  date: 2026-09-11
  baseline_commit: 2c6b5e3
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-11T19:33:52.816117+08:00"
updated_at: "2026-09-11T19:33:52.816117+08:00"
---