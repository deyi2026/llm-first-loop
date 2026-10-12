---
title: 工具使用最优路径：先复用已验证套路，失败只做定向修正
scenario: 用户要求“特别是工具的使用，及时总结最优的工具使用方法经验”，适用于高频工具调用任务（抓取/检索/评估/文件修改等）。
root_cause: 工具调用低效通常来自两类：重复探测已知道的套路（多余 search/重试/环境探测），以及失败后未按错误类型做定向修正（参数错误仍原样重试）。
solution: 执行前先匹配已验证的最短路径：已知套路直接走最短链路；失败后先读错误类型，参数错误改参数、权限/开关错误换授权路径、瞬态网络错误才 retry_tool；连续同类失败即停止试错，交付可执行替代方案。每次形成新最优解或踩到新参数约束，立即 save_experience 落盘，后续同场景优先复用。
evidence: 历史记忆：用户批评文章总结调用约10次工具，约定“头条→execute_command+curl+解析 RENDER_DATA”最短路径；本轮 self_evaluate 首次 trigger 自然语言失败，定向改为 manual 后成功，并已沉淀 EXPERIENCE-20260816-self-evaluate-trigger.md。
tags: [工具使用, 最优路径, 定向修正, 效率, 经验沉淀]
source:
  origin: user_directive_tool_use_best_practice
  related_experience: EXPERIENCE-20260816-self-evaluate-trigger.md
status: active
created_at: "2026-08-16T13:43:27.333014+08:00"
updated_at: "2026-08-16T13:43:27.333014+08:00"
---