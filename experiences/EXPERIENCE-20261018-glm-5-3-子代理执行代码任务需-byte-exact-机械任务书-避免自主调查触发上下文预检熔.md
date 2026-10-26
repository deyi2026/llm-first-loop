---
title: glm-5.3 子代理执行代码任务需 byte-exact 机械任务书，避免自主调查触发上下文预检熔断
scenario: 调度 glm-5.3 子代理执行代码修订任务（LFL 主会话统筹，子代理无持久 ArchiveStore）
root_cause: ""
solution: 统筹者先自行取证并把任务书降为 byte-exact 机械执行：预先读原文、写出每个 edit 的精确 old/new 串与测试设计嵌入任务书，明确禁读清单外文件；agent 只做执行+验收
evidence: 本会话观察链：subagent_220e93be5bdc 与 subagent_00d19b6842c7 先后死于上下文预检（工具轨迹只有 read/search 无 edit）；随后 subagent_799ef0e42aff（接线）、subagent_0680bdbc2790（P1/P2 修复）、subagent_65c147fd542a（env 开关删除）三类 byte-exact 任务书均一次通过，验收全绿，最终经独立审核 r1'-r3 与全量门禁 exit=0。
tags: [spawn_subagent, 任务书设计, 子代理窗口, 上下文预检]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-18T14:49:16.299227+08:00"
updated_at: "2026-10-18T14:49:16.299227+08:00"
---

现象：spawn_subagent（glm-5.3）执行代码任务时，若任务书只给目标与验收、让 agent 自主调查设计，agent 会连续读文件+长推理至接近窗口，触发"子代理上下文预检失败：无 search_archive/ArchiveStore，拒绝静默截断"熔断退出（本例连续 2 次：97875/40324 tokens_in）。对策：主代理先自行收集事实（读原文、定位行号、查 baseline 结构），把每个编辑写成 byte-exact old_string/new_string 与精确测试设计嵌入任务书，agent 降级为机械执行+验收。效果：同规模任务一次通过（3/3 成功）。适用边界：改动范围明确、可预先枚举时最优；真正需要开放探索的任务仍需留自主空间，此时应缩小任务范围或分批 spawn。失败处理：edit_file 工具在子代理环境不可用时，agent 可用 shell 内 Python 字节级替换（断言恰好出现 1 次）替代，验收仍以 ruff/pytest 为准。