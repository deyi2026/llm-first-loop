---
title: exec 沙箱边界错位：服务进程从旧 seatbelt 通道出生导致 scoped write 持续 EPERM
scenario: "LFL web 服务进程在 23:17 从带旧 seatbelt 沙箱的父通道出生；00:22 已给 exec 通道授予对 /Users/yyj/Project/research/runtime 的 scoped write，但 agent exec 探针仍 EPERM。同一探针在用户自己的干净通道（Terminal.app exec 链）WRITE-OK，证明授权配置本身正确，错位在 web 进程出生时继承的旧沙箱快照。"
root_cause: ""
solution: "遇到\"授权已更新但 exec 仍 EPERM\"时，先做通道二分：用户干净通道跑同一 probe。若用户通道通过而 agent 通道失败，则问题在进程出生上下文而非配置——macOS 沙箱(seatbelt/TCC)是进程出生时的快照，不会随后续授权更新追溯生效。修复动作：让用户从干净通道重启服务进程，新进程继承新授权。无需反复重试命令或调整授权路径。"
evidence: "前: LFL exec 探针 touch /Users/yyj/Project/research/runtime/.write-probe → EPERM(Operation not permitted)，ps 亦 EPERM；用户 Terminal 通道同 probe WRITE-OK。后: 干净通道重启 web(PID 39045→96030, generation 86, git_head 9bcc2a98d, /auth/status 200)，LFL exec 同 probe 输出 WRITE-OK 退出码 0。"
tags: [sandbox, seatbelt, process-inheritance, service-restart, exec-boundary, macos]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-24T00:49:22.669920+08:00"
updated_at: "2026-09-24T00:49:22.669920+08:00"
---

排查路径：先二分定位——用户通道(实证可写的 Terminal exec 链)同 probe 通过、agent exec 失败 → 排除授权配置错误，指向 web 进程自身；再查出生时刻(23:17 的父通道 vs 00:22 的新授权)确认继承错位；通道内连 ps 都 EPERM，从内部无法走祖先链取证，只能靠用户侧出生上下文记录。修复：用户从干净通道重启 web(新 PID 96030)，同探针即恢复。关键教训：授权/沙箱是进程出生时快照，不随配置更新追溯；"改了配置还不行"时第一怀疑对象应是"进程比配置老"。