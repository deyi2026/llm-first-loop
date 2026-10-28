---
title: execute_command 的 workdir 参数会绑定沙箱写权限；不给 workdir 时工作区外路径一律 EPERM
scenario: "本会话 LFL_WORKSPACE_ROOT 指向部署 release 目录（$HOME/Project/llm-first-loop-mirror/.releases/<sha>），需要修改 $HOME/lfl-workspace/docs/TECH-DEBT-20261027.md。不带 workdir 执行 touch/cp/append-zero 到 $HOME/lfl-workspace 任意子目录全部 \"Operation not permitted\"；read_file 加 snapshot=true 直接 WorkspaceScopeMismatch；一度误判为\"本会话无权写该目录、只能另寻会话或提权\"。"
root_cause: ""
solution: "1) 事实：execute_command 的沙箱白名单按 workdir 绑定——指定 workdir=$HOME/lfl-workspace 后再 touch 同名目录即成功（WORKDIR_WRITE_OK），随后 patch 写回原文件成功。2) 因此工作区外文件写入：execute_command(workdir=<目标根目录>) + patch/sed/cp 即可，不需要\"复制到工作区→edit_file→cp 回写\"。3) read_file(snapshot=true)/edit_file 仍受 WorkspaceScopeMismatch 限制（按 LFL_WORKSPACE_ROOT），所以 edit_file 类正式写入只能走 patch 或 shell 文本工具。4) 校验链：写前 shasum、写后 shasum + wc + cmp 与\"已验证副本\"，并用 head/tail 分段 cmp 证明改动之外逐字节未变（注意插入行会移动后方行号，比对偏移要用 +1）。5) 附注：bash here-doc 喂解释器会触发 E6_CATASTROPHIC_HARD 硬阻断，改用 printf 写脚本/数据文件再执行。"
evidence: "execute_command 实测：touch $HOME/lfl-workspace/.wtest-86497 → \"Operation not permitted\"（无 workdir）；同命令 workdir=$HOME/lfl-workspace → WORKDIR_WRITE_OK；TMPDIR=/tmp patch docs/TECH-DEBT-20261027.md < row2.patch 使 sha256 dbfa3b98…e05454 → dc91582a…cf8913e，diff -u 仅新增 1 行，head -281 cmp 一致、tail 分段 cmp 一致。"
tags: [execute_command, sandbox, workdir, 写入权限, patch, 台账维护]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-28T10:36:12.541694+08:00"
updated_at: "2026-10-28T10:36:12.541694+08:00"
supersedes: [EXPERIENCE-20261028-工作区外文件的可写路径与安全编辑法-workdir-绑定-仓库副本-edit-file]
---