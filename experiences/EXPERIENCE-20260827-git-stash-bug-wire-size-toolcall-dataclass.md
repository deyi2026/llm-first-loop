---
title: 基线判定法（git stash）区分既有 bug 与新改动 + _wire_size ToolCall/dataclass 双形态兼容
scenario: 镜像区执行 T-P0-1-1（reasoning_tail 默认值 2→0）时触发 test_reasoning_tail_recent_round_with_tool_calls_kept 失败，需判定失败归属（新改动 vs 既有 bug）
root_cause: 新增 _wire_size 统计函数（2026-08-26 死循环修复引入）按 OpenAI wire dict 嵌套结构解析 tool_calls，未覆盖 Message 内部 ToolCall dataclass 扁平结构，带 tool_calls 的 assistant 消息进入预算统计路径即崩
solution: ①基线判定：git stash → pytest 复现 → stash pop，三步确认既有 bug 与改动无关；②grep 根因：_wire_size 假设 wire dict 结构而 Message.tool_calls 是 ToolCall dataclass；③isinstance 分支兼容修复 + 单测验证 4/4 绿 + 全量回归 exit=0
evidence: git stash 基线复现同样失败；修复后 pytest tests/unit/test_reasoning_tail.py 4/4 全绿；ruff 全过；全量单测 exit=0
tags: [testing, bug-fix, baseline-verification, dataclass-compat, history]
source: {}
status: active
created_at: "2026-08-27T02:01:47.254875+08:00"
updated_at: "2026-08-27T02:01:47.254875+08:00"
---

发现：pytest test_reasoning_tail.py 单例失败 AttributeError: 'ToolCall' object has no attribute 'get'（history.py:37）。判定法：git stash && pytest（复现同样失败）&& git stash pop——基线同样失败即证明为既有 bug，与当前改动无关，避免误回滚自己的修改。根因：_wire_size 统计函数假设 tool_calls 是 OpenAI wire dict 嵌套结构（tc["function"]["name"]），但 Message.tool_calls 实际是扁平 ToolCall dataclass（name/arguments 直属字段）。修复：isinstance(tc, ToolCall) 分支兼容两种形态。风险背景：该函数是 2026-08-26 glm 超限死循环修复引入的新口径统计（_wire_size），上线时未被带 ToolCall 对象的测试路径覆盖——提示新增统计/校验函数时应同步补对 dataclass 与 wire dict 双形态的测试。