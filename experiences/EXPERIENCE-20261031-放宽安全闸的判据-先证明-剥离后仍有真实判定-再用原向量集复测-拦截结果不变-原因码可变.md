---
title: "放宽安全闸的判据：先证明\"剥离后仍有真实判定\"，再用原向量集复测\"拦截结果不变、原因码可变\""
scenario: command_scope_guard 对 heredoc 与未加引号分组一律拒绝（`unmodeled_shell_construct`），造成 `cat > f <<EOF`、`(cmd)` 这类写目标本可静态判定的用法被误伤。要放开就必须证明不引入绕过。
root_cause: "原实现用\"命令文本形态\"而不是\"写目标是否可静态判定\"作为拒绝依据；heredoc 正文会污染 token 流、分组括号会被当成裸 token，所以干脆整体拒。放开的前提不是\"看起来安全\"，而是\"剥离后仍存在真实判定对象\"。"
solution: "三段式：①剥离前在**原始串**级别拒执行向量（$(…)/反引号/进程替换），因为未加引号 heredoc 分隔符只开启参数/算术展开、两者都不执行命令——这条是\"正文剥离后仍安全\"的唯一依据，必须显式写成前提而非隐含假设；②按 bash **精确**语义匹配 heredoc 终结符（`<<X` 必须恰为 X，`<<-X` 只剥前导 tab），口径比 bash 松会让\"剥离\"变成\"吞掉真实命令\"，找不到终结符一律拒；③放开后把原来那套绕过向量集原样重跑，验收口径定为\"**拦截结果不变，原因码可变**\"（`(rm /outside/x)` 由 unmodeled 变 write_target_outside_scope 仍算通过），并逐条列出未放开的残余（花括号分组、引号内字面量括号、`( … ) > f`）。"
evidence: "§16.8 十二类 + §16.9 七类共 25 条向量复测 25/25 仍拦 0 漏；tests/test_command_scope_guard.py 445 passed；-k \"scope or execute_command or heredoc or guard\" 1602 passed；./scripts/ci_gate.sh --quick exit=0，tier0 329 passed/2 skipped"
tags: [安全闸, 误伤, fail-closed, 回归向量, heredoc]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T15:45:41.085916+08:00"
updated_at: "2026-10-31T15:45:41.085916+08:00"
supersedes: [EXPERIENCE-20261030-绕过向量回归锁须用最宽-scope-断言拒绝理由-受限-scope-下的-已拦-可能是错因拒绝]
---