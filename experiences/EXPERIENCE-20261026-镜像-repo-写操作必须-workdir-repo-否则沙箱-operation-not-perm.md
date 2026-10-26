---
title: 镜像 REPO 写操作必须 workdir=REPO，否则沙箱 Operation not permitted
scenario: 在 REPO=~/Project/llm-first-loop-mirror 与工作区 ~/lfl-workspace 并存的双根环境下，用 execute_command 把工作区改好的文件 cp 回 REPO。
root_cause: ""
solution: 所有写 REPO 的命令（cp 回写、git add/commit 等）必须显式传 workdir=REPO，不能用默认 workdir 或 cd 链；写工作区则用默认 workdir。读 REPO 任意方式均可。
evidence: "失败回执：cp → REPO src/llm_loop/tools/review_host_admission.py \"Operation not permitted\"（workdir 默认）；成功回执：同 cp + workdir=~/Project/llm-first-loop-mirror → CP_OK + git diff --stat 110 insertions。"
tags: [sandbox, workdir, cp, mirror-repo]
source:
  command_fail: cp <ws>/review_host_admission.py <REPO>/src/... (no workdir) -> Operation not permitted
  command_ok: cp <ws>/review_host_admission.py src/llm_loop/tools/... (workdir=REPO) -> CP_OK
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T12:45:53.904111+08:00"
updated_at: "2026-10-26T12:45:53.904111+08:00"
---

现象：execute_command 默认 workdir（工作区根）下，对 REPO=~/Project/llm-first-loop-mirror 的任何写（touch/重定向/cp 覆盖）均报 "Operation not permitted"，文件权限位与 flags 均正常。原因：macOS sandbox-exec 沙箱只授权"当前 workdir + 工作区/缓存目录"的写。修复：同一 cp 命令加 workdir=REPO 后成功。推论：委派链里的"git 写必须 workdir=REPO 不能 cd 链"同样适用于 cp 回写与一切落盘命令。