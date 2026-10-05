---
title: 先入为主前提未验证即进入修复循环：连续 4 次无效尝试（mlx_lm 内存事故过程教训）
scenario: "服务出现\"巨大内存占用+生成速度急剧变慢\"症状（mlx_lm.server 托管 Ornith-1.5-35B-A3B-MLX）时，先入为主认定\"并发参数 2/2 是根因\"，未核对当前实际运行参数与症状时间线，即连续提交 4 次并发参数修复尝试，全部无效。"
root_cause: "把第一直觉当作已核事实进入修复循环；对\"并发参数是根因\"这一前提未做任何当前证据核对"
solution: "症状归因前先核当前事实（实际运行参数、日志、时间线）；把\"假设 X 是根因\"当作待验证命题而非前提——一次反证（参数实为 1/1 且多开恢复正常）即可排除并发假设；排除后再扩大检索面。本事故最终根因：模型名未命中别名触发 HuggingFace 在线解析，修复=全名别名+HF_HUB_OFFLINE=1。"
evidence: "experience:EXPERIENCE-20260911-mlx-lm-huggingface-hf-hub-offline-1（已记录：误判并发 2/2→4/4，证伪=当前运行参数实为 1/1 且多开恢复正常；最终修复=全名别名+HF_HUB_OFFLINE=1）；episode:932df416-c651-4aff-9348-962d36f4ff73:13:1bdb3bd9b931e99a61b2（2026-10-03 复核引用\"连续 4 次修复尝试\"）"
tags: [premise-check, incident-forensics, attribution, discipline, system-prompt-rule1-support]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-03T06:04:31.487275+08:00"
updated_at: "2026-10-03T06:04:31.487275+08:00"
---

症状归因前先核当前事实（运行参数、日志、时间线），把"假设 X 是根因"当待验证命题而非前提；一次反证即可排除假设并转向扩大检索面。反例：mlx_lm 服务"巨大内存+变慢"被先入为主归为并发参数，未核当前参数即连续 4 次修复尝试，全部无效；真根因是模型名未命中别名触发 HuggingFace 在线解析。