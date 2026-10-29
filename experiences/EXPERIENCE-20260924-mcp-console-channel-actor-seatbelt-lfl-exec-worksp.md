---
title: MCP Console channel-actor 的 seatbelt 是 LFL exec 边界真身：写域=通道 workspace，EPERM/ps 禁/观察器失败同根因
scenario: agent 的 execute_command 对工作区外（如 /Users/<user>/Project/research/runtime）写入报 Errno 1 EPERM、ps 被拒、lfrt 写类子命令（restart/stop 触碰 config.json.lock）失败、LFL local_runtime 观察器永远 observation_failed、runtime 准入门（admission_authority=lfrt）永远关着
root_cause: ""
solution: "根因：LFL 会话跑在 MCP Console coding_tools 为通道（LFLM, id 4dbbf4ec）派生的 channel-actor 里，seatbelt 可写域=通道 workspace（llm-first-loop-mirror），mode=dangerous 只免确认不解沙箱。修复：在 MCP Console 通道设置（codingFilesystemScope 等）为 research/runtime 增加可写根，或维持 runbook 模式（模型出操作、用户在 Terminal.app 执行；lfrt 须用全路径 /Users/<user>/Project/research/runtime/lfrt 或先 cd 进目录，它不在 PATH）。"
evidence: "evidence://v1/994dd7443b56a90d0620788f706088c94bcee14939ea2b3b8f2d7509fd4eed21"
tags: [mcp-console, seatbelt, sandbox, lfrt, eperrm, local_runtime, admission]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-24T00:31:13.894228+08:00"
updated_at: "2026-09-24T00:31:13.894228+08:00"
---

证据链：(1) sidecar-console.log: "mcp_console::coding_tools: 通道 Runtime 已就绪（channel-actor）channel=4dbbf4ec workspace=/Users/<user>/Project/llm-first-loop-mirror mode=dangerous"；(2) 探测：mirror 内 touch OK，/Users/<user>/Project 根 touch EPERM，ps 本身 EPERM（process-info 被拒）；(3) lfrt status --json 可读但 process:null（lfrt 内部 ps 被继承沙箱拒绝）→ runtime-observation state=unknown → local_runtime observation_failed；(4) MCP Console 无 App Sandbox entitlement（codesign 空），是应用显式 sandbox-exec；(5) ~/Library/LaunchAgents 无沙箱痕迹，web 服务(39045)命令行干净、PPID=1。修复旋钮在 MCP Console 通道设置：codingWorkspace / codingFilesystemScope / codingPermissionMode。与 EXPERIENCE-20260914（research 树只读）同根因，该经验补齐了"谁套的沙箱、开关在哪"两块。