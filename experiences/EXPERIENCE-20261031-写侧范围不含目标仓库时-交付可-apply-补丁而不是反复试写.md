---
title: 写侧范围不含目标仓库时，交付可 apply 补丁而不是反复试写
scenario: LFL 会话写侧范围是 LFL_WORKSPACE_ROOT（本次为 llm-first-loop-mirror/.releases/b008c9fae…），而交接文档所在的 /Users/<user>/lfl-workspace 不在其中：edit_file 取 snapshot 报 WorkspaceScopeMismatch，shell 写探针 touch 报 Operation not permitted（sandbox-exec 只放行工作区与缓存目录）。此时 read_file/search_files 仍可读，形成「读得了、写不了」的错觉。
root_cause: ""
solution: 先用两条独立证据确认边界（edit_file snapshot 失败 + shell 写探针失败），不要反复试写。然后在唯一可写且可呈现的根内产出 unified diff：在 /tmp 建临时 git 仓库（复制 base→git init/add/commit→覆盖为新版→git diff）得到带 a/ b/ 路径的补丁；用 `git -C <目标仓库> apply --check <patch>` 做只读预演（不写入目标仓库）；最后把 .patch 与 README 放到可写根并 present_files，README 里写明「已在目标仓库根预演通过、尚未应用」以及不要 commit 进生产仓。
evidence: "edit_file(snapshot=true) 对 <WS> 路径返回 WorkspaceScopeMismatch；execute_command 写探针返回 Operation not permitted（WS）/ 成功（镜像仓 docs/design 与 /tmp）；git -C /Users/<user>/lfl-workspace apply --check 返回 APPLY CHECK: OK"
tags: [workspace-scope, sandbox, patch-delivery, handoff]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T15:05:41.135161+08:00"
updated_at: "2026-10-31T15:05:41.135161+08:00"
---