---
title: 合并后测试随运行线 API 演进：env 开关 → 参数注入的适配时序
scenario: 分支测试依赖某全局配置开关（env var）驱动工具行为；运行线把该开关改为函数参数注入，git 合并零冲突（文本层无重叠）但测试逻辑失效。
root_cause: ""
solution: "合并/上新线后不信任\"合并零冲突\"：先对 OWN 测试文件重跑，失败时 diff 运行线该函数签名，把 env 设定改为 kwargs 调用；测试语义断言保持不变。"
evidence: "commit f6e154cd（4 处精确替换，tests/unit/test_injection_ledger.py）；45 例全绿后推进 gen8；对应 method:lfl-mirror-qualified-worktree-33ba78f2f2e7 新增适配规则。"
tags: [merge, api-evolution, tests, lfl-deploy]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-17T22:27:44.424182+08:00"
updated_at: "2026-09-17T22:27:44.424182+08:00"
---

mirror 主线把 LFL_TOOL_GUIDANCE 环境变量收敛为 tool_result_to_message(tool_guidance_mode=) 参数注入（R8.24-C）。分支上的测试用 monkeypatch.setenv 设 env，合并到含此改动的运行线后全部失败：回执无引导文本、ledger 无 receipt_pointer 行。修复 = 测试显式传 kwargs（on/off），断言不变。教训：合并接口变更后的第一动作 = 用运行线当前 API 重写 OWN 测试的调用面，env 开关注定失效。