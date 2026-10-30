---
title: "绕过向量回归锁须用最宽 scope + 断言拒绝理由：受限 scope 下的\"已拦\"可能是错因拒绝"
scenario: "给写侧/权限/安全闸补回归用例时，用受限 scope（如 paths=(\"src/**\",)）复测绕过向量，看起来\"全被拦\"就收工；实际拦下的是无关操作数，真实写目标越界仍放行。第五轮独立审查（write_scope P1-a 命令族闸）实证：15 条绕过向量在受限 scope 下全被拒，换 paths=(\"**\",) 后 15/15 全部 ALLOW。"
root_cause: "判定层的拒绝可能来自与真实写目标无关的因素（拒了操作数、拒了 cwd 相对路径解析、拒了不可定位的名字）。受限 scope 下这些无关因素先命中，掩盖了\"闸没拦住真实写目标\"的真问题；且用例只断言 allowed==False，不查 reason ⇒ 假通过。"
solution: "1) 回归锁的判定基准用**最宽 scope**（paths=(\"**\",)），让\"真实写目标越界\"成为唯一拒绝理由；2) 用例**同时断言拒绝理由**（expected_reason），把\"错因拒绝\"暴露成红灯；3) 补一组\"读形态仍放行\"的对照用例防过度拦截（如 git symbolic-ref HEAD / tar -xf a.tar -C src / gcc --version / env -C src ls）。4) 配套自证伪：把闸打成恒放行，每条应拦用例必须变红（防\"用例测的是空转\"）。"
evidence: "实测（2026-10-30 22:24–22:33，llm-first-loop-mirror）：scope=paths=(\"src/**\",) 下 15 条向量\"全被拦\"；scope=paths=(\"**\",) 下 15/15 ALLOW（真实绕过）；修复后 scope=(\"**\",) 下 15/15 拒绝且 reason 逐条匹配预期，判定层 175 passed（含新增 14 条应拦 + 4 条放行形态），ruff 干净。"
tags: [回归测试, 安全闸, 写侧授权, 错因拒绝, 独立审查, RULE-AI-35]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T22:36:45.316089+08:00"
updated_at: "2026-10-30T22:36:45.316089+08:00"
---