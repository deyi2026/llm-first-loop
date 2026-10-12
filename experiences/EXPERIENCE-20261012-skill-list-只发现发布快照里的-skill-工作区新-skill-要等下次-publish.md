---
title: skill_list 只发现发布快照里的 skill，工作区新 skill 要等下次 publish 才入注册表
scenario: 新建 skills/&lt;name&gt;/SKILL.md 后用 skill_list 检索不到新条目；怀疑写入失败或 skill_list 有过滤。skill_list 回执显示所有条目路径在 .releases/5a4b47a…/skills/（发布快照目录），而新文件在工作区 skills/ 下。
root_cause: ""
solution: skill 注册表从发布快照发现 skill，不从工作区实时发现。新 skill 有两条可用路径：(1) 立即用=直接 read_file 工作区 SKILL.md 路径（不依赖注册表）；(2) 注册表可见=等下一次 publish 绑定当前树后自动进入。验证写入是否成功用 ls/read_file，不要用 skill_list 判断文件是否存在。
evidence: 2026-10-12 实测：skill_list 回执 33 项全指向 .releases/5a4b47ac402dd23817bf49b00d3945617a78e9c8/skills/ 且无新建的三个 gate skill；ls .releases/5a4b47ac…/skills = 33 项（无 article/code/push-review-gate），ls skills/ = 34 项（含三者）；ls -ld .releases/…/skills 显示为普通目录（非 symlink），证明是发布时复制的快照。
tags: [skill-registry, release-snapshot, publish, skill-discovery]
source: {}
status: archived
record_kind: experience
verification_state: verified
created_at: "2026-10-12T22:57:26.507034+08:00"
updated_at: "2026-10-12T23:27:58.991366+08:00"
supersedes: [EXPERIENCE-20260911-skill-shell-skill-list]
---

现象：在 workspace skills/ 下新建 skill 后，skill_list 清单里不出现；清单条目路径全部指向 .releases/&lt;commit-hash&gt;/skills/。
判据：.releases/&lt;hash&gt;/skills/ 是发布时从 git 树复制的不可变快照（ls -ld 显示为普通目录非符号链接）；workspace 与快照条数可差（实测 34 vs 33）。
处理：新 skill 写入 workspace 后 (1) 立即可用方式=子代理/父会话直接 read_file 读 workspace 路径；(2) 注册表可见=等下一次 publish 以当前树出快照；(3) 验证技巧=skill_list 回执里 grep 新名字，发现不了先查 .releases/&lt;当前hash&gt;/skills/ 有没有，别误判为"写失败"。
边界：skill_load 按名字加载同样走注册表；按路径 read_file 的用法不受快照约束。