---
title: 沙箱内门禁假新红的两类根因：继承 LFL_SKILLS_REQUIRE_MANIFEST=1 + 无 PTY 设备——base 对照 + env -u + openpty 探针三步归因
scenario: 在 agent 沙箱（macOS sandbox-exec，execute_command 继承 LFL 运行时环境）内跑仓库全量门禁，出现几十条「未登记新红」（terminal_pty 全组、skills_loader/skill_tools 组、env_channel 组），需要判定是代码回归还是环境伪红，否则会误改基线/误判候选不可推。
root_cause: "沙箱两类环境差异：(1) LFL 运行时进程预设 LFL_SKILLS_REQUIRE_MANIFEST=1（仓库默认 0，ci_gate.sh 与 pyproject 都不设），使技能完整性门禁在发现侧生效，隐藏未登记技能 → skills_loader 组红；(2) macOS 沙箱无法分配 PTY（/dev/ptmx 存在但 pty.openpty() 抛 OSError: out of pty devices）→ terminal_pty 全组红；(3) env_channel 那对测试是 skipif 守卫——沙箱专用那条只在沙箱内跑（沙箱内红）、非沙箱那条在普通终端跑（沙箱内 skip）。"
solution: 三步归因，缺一不可：(1) base 对照——在同一沙箱环境跑父提交 worktree 的同一批测试，比较失败集合逐条差异（集合一致=环境红；仅多出少量=真回归）；(2) env -u 探针——清掉继承来的 LFL_SKILLS_REQUIRE_MANIFEST 后重跑受影响文件，红消失即证明是环境污染而非代码缺陷；(3) openpty 探针——用 python -c 'import pty; pty.openpty()' 直接探 PTY 分配能力，失败即证明 terminal_pty 组不可在沙箱消除（须换有 PTY 的真实终端跑权威门禁）。结论：不要为迎合沙箱改基线、改代码或登记豁免；应把权威门禁交回有 PTY 且无该 env 的真实终端执行。
evidence: "候选 62939c22a 与 base 55b53ab8 在同沙箱环境全量同红 34 条（PTY 26 + skills 7 + env_channel 1），逐条一致（/tmp/base_fails.txt vs /tmp/r9_gate_last.log）；env -u LFL_SKILLS_REQUIRE_MANIFEST 后 skills 三文件 50 passed/1 failed（仅剩 env_channel 沙箱专用条），skills_loader 5 红与 skill_tools_p1a 2 红全消（/tmp/skills_cand.log）；pty.openpty() → OSError: out of pty devices；候选真实红只有 1 条棘轮（tests/unit/test_arch_guards.py::test_function_lines_ratchet_within_baseline），base 同文件 40 passed（evidence://v1/b19014f6ad3c55f9b55af75415f31991d07fa75a2a64e69fa4d267cbbf0dfdf7）"
tags: [ci_gate, 沙箱, 假新红, base对照, PTY, env污染, 归因]
source:
  branch: integrate/main-20261031
  project: llm-first-loop-mirror
  task: 整合待推集门禁与推送
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T23:18:05.035147+08:00"
updated_at: "2026-10-31T23:18:05.035147+08:00"
supersedes: [EXPERIENCE-20261025-沙箱内跑-ci-gate-的批量假新红-用-base-worktree-逐条对照失败集合归因-别改基]
---