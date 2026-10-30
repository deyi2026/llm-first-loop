---
title: 证据产物入库前先自查文件体积与本机绝对路径
scenario: 要把机械扫描/评审产生的证据产物（逐卡清单 JSON）提交进带 git 安全扫描的仓库。
root_cause: ""
solution: 入库前先自查两项：(1) 单文件体积上限（本仓 1MB）——超限不硬塞，改出「发现子集」（只含命中条目 + 统计 + 复现命令），全量文件由文档记录的同一命令复现；(2) 本机绝对路径——replay_command 里的仓库根前缀（<本机仓库根路径>）会触发扫描，入库前统一改写为仓库相对「.」，并在产物的 note 里写明改写了多少处、语义不变。改完再 grep 一次 常见本机绝对路径前缀（家目录/root/盘符），确认 0 命中。
evidence: "本轮两次被真实拦截：reports/qualification-r4/mech-all-sample.json 1.28MB → 命中「文件过大 (1281120B > 1MB)」；mech-findings.json 含 292 处 <本机仓库根前缀> → 命中「本地绝对路径匹配」。改写后入库成功（312KB，绝对路径 0 命中，cwd 均为 \".\"），四轮独立审查的 P2-2 亦复现同一发现并要求推送前自查，已照办。"
tags: [git, 安全扫描, 证据产物, 入库]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T13:18:54.534001+08:00"
updated_at: "2026-10-30T13:18:54.534001+08:00"
supersedes: [EXPERIENCE-20261028-批量入库未跟踪知识资产-安全扫描要在-add-之后扫-staged-全集-提交信息要按类核对]
---