---
title: 子代理文件工具作用域≠仓库：跨域写代码必须走 execute_command(workdir=REPO) 的 cp 通道
scenario: LFL 运行环境（2026-10-25 起）：子代理/主会话的文件工具作用域与 git 仓库分离（工作区根=~/lfl-workspace，REPO=~/Project/llm-first-loop-mirror），需要跨界读写仓库代码时
root_cause: ""
solution: "派代码子代理的任务书里固定写\"写入通道\"一节：读=execute_command(workdir=REPO)+sed/grep；改=cp 到工作区→edit_file→cp 回（workdir=REPO）；禁 here-doc 喂解释器；禁 python 进程内直写 REPO。主会话自己改仓库文件同样走\"工作区副本+cp\"或 execute_command(workdir=REPO)。另：给子代理设工具轮上限与\"每 N 轮必须落一次盘\"的硬约束，防纯读空转。"
evidence: 子代理 subagent_fc4daee04bdd 报告实测（WorkspaceScopeMismatch 原文 + touch WRITE_OK 探针）；父会话复现：read_file(snapshot=true) 对 ~/Project/llm-first-loop-mirror/docs/HELDOUT-GUARD-20261025.md 报 WorkspaceScopeMismatch；doc_patch.py 无 workdir 直写 REPO 报 PermissionError，cp+workdir=REPO 成功（docs/HELDOUT-GUARD-20261025.md §6-1 已改写落盘）；后台 job 写探针 reports/phase4/m0/_bgprobe.txt（workdir=REPO）BG_WRITE_OK。
tags: [subagent, workspace-scope, sandbox, execute_command, write-channel]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-25T20:55:36.360336+08:00"
updated_at: "2026-10-25T20:55:36.360336+08:00"
---

现象：子代理与主会话（重启后）的 read_file/edit_file 对仓库路径直接报 WorkspaceScopeMismatch——文件工具的作用域是进程工作区根（~/lfl-workspace），不是 git 仓库。早期派出的两个代码子代理因此零产出（一个被误判"卡死"取消，一个 88 轮空转后 completed）。已验证通道：(1) 读仓库：execute_command(workdir=REPO, command="sed/grep/git ...")；(2) 改文件：cp 仓库文件→工作区，edit_file 改副本，再 execute_command(workdir=REPO, command="cp 工作区副本 REPO 路径")；(3) execute_command 的写权限跟随 workdir 参数——workdir=REPO 时 REPO 可写（后台任务同样），命令内 cd 而不带 workdir 时 REPO 写被拒（EPERM）；(4) python 进程内写"命令行不可见的路径"会被沙箱拒绝（例：doc_patch.py 从工作区 cwd 直写 REPO 文档 → PermissionError），必须走 cp 或 workdir。here-doc 喂解释器（python - <<PY）被安全硬阻断，here-doc 喂 cat 写文件允许。给子代理派活时必须把通道写进任务书（附具体命令样例），否则大概率空转。