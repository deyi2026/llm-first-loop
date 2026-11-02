---
title: exec 全线 EPERM：auto 沙箱后端只探二进制存在，嵌套沙箱环境必然误判可用
scenario: "运行时代理从已被外层 sandbox-exec 包裹的运维通道拉起（服务进程继承调用方沙箱）后重启，工具层每次 execute_command 都返回 exit 71 / \"sandbox-exec: sandbox_apply: Operation not permitted\"。现象与\"profile 写错\"无关：后台模式同样失败（派发回执是 success，但进程终态仍是 71，别把受理当成功）。根因：src/llm_loop/tools/sandbox.py 的 auto 解析只判断 /usr/bin/sandbox-exec 是否存在且可执行，不验证能否真的套用 profile；嵌套环境必然误判为可用，于是每条命令都在套 profile 阶段 EPERM。"
root_cause: ""
solution: "1) 判据改为实跑探测：用一条最宽松 profile（(version 1)(allow default)）实跑 /usr/bin/true 一次，进程内缓存结果；套用被拒（stderr 含 sandbox_apply / Operation not permitted）即判不可用。2) auto 解析在 sandbox-exec 不可用时继续落到 docker→none，并把\"存在但套 profile 被拒（可能已被外层沙箱包裹）\"写进 reasons 与 warning，不静默降级。3) 显式 mode=\"sandbox-exec\" 同样受该探测约束：不可用则 fail-closed，但错误信息要给可读原因而不是裸 EPERM。4) 临时解法：.env（gitignored）写 EXEC_SANDBOX=none + 重启承载会话的服务进程生效；代码修复上线后删掉该行。5) 编辑 .env 要匹配整行（含行尾全角标点）：只匹配行首前缀会留下\"EXEC_SANDBOX=none：\"这种非法值。"
evidence: "evidence://v1/91e461c29aaedeecc852eb0d21142a07c4f2e88594ce567f8a98efc01436005b（后台 execute_command 仍 exit 71）；evidence://v1/26cd81dcac505eb252a12ae40e6b1240fffcbe4aa1083f27a9aed55ddab27801（官方 review_admission PASS，证明 material_diff 阻塞已解除）；src/llm_loop/tools/sandbox.py 已写入 _sandbox_exec_applicable + _probe_sandbox_exec 改判定 + reset_auto_cache 清理新缓存；tests/test_sandbox_backend.py 已补 3 条用例并改 _patch_backends——尚未提交、尚未跑测试，故记 unverified"
tags: [exec, sandbox-exec, nested-sandbox, EPERM, runtime, macOS]
source: {}
status: active
record_kind: lesson
verification_state: unverified
created_at: "2026-10-31T22:40:01.556887+08:00"
updated_at: "2026-10-31T22:40:01.556887+08:00"
supersedes: [EXPERIENCE-20261028-execute-command-的-workdir-参数会绑定沙箱写权限-不给-workdir-时工]
---