---
title: 双仓工作区：edit_file 成功不等于写进了目标仓库
scenario: "LFL 会话运行于 mirror（/Users/yyj/Project/llm-first-loop-mirror），但用户任务仓库是主区（/Users/yyj/Project/research/s1-producer-research）。edit_file 的相对路径以会话工作区根（mirror）解析，报告\"success + 写后复读一致\"，而 shell 子进程对主区全路径 EPERM（运行时刻意写墙），绝对路径 edit_file 被拒。表面上工具链一切正常，实际改动从未到达目标仓。"
root_cause: "edit_file 的 workspace root 随会话实例（zone=镜像）而非用户任务仓库；工具成功语义只覆盖\"写入某路径且复读一致\"，不含\"写入了用户意图的仓库\"。"
solution: "跨仓任务中，任何\"写成功\"之后立即用独立通道复核目标：shasum -a 256 目标绝对路径 vs edit artifact 记录的 sha256；或 sed -n 直接看目标文件头部。git apply --check 是只读验证补丁可落性的好工具（不写盘）。产出交付物（diff）到 /tmp 并给用户自落，比硬闯写墙或提交边界演进更符合\"不擅自放宽边界\"原则。"
evidence: "mirror 文件 sha256 f3212ad8be4e2b2ecff1359f6cb3eac00f98ec4e9088517671d2a20e32fa7f69 == 两次 edit_file artifact sha；主区文件 sha 2c21488944f2291c07d30b9337f21617fd3a95c4ebe83bb73457b89552065aae（原值未动）；sed -n '1,30p' 主区文件无 fixture。"
tags: [workspace-identity, edit_file, mirror, write-wall, verification, dual-repo]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-11T04:07:56.084876+08:00"
updated_at: "2026-09-11T19:33:52.803613+08:00"
last_verified_at: "2026-09-11T19:33:52.803613+08:00"
---