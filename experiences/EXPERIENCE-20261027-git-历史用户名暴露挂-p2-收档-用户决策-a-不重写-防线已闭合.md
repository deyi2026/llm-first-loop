---
title: git 历史用户名暴露挂 P2 收档（用户决策 A：不重写，防线已闭合）
scenario: llm-first-loop-mirror 仓库 git 历史提交中存在本机用户名路径暴露（/Users/<user>），需决策是否 filter-repo 历史重写；用户在 A（挂 P2 收档）与 B（重写+force-push）之间选择。
root_cause: ""
solution: "用户 2026-10-27 22:27 确认 A：挂 P2 收档。登记内容：历史暴露仅用户名 <user>（密钥/IP 零命中）；现行防线=当前树脱敏 14 卡 24 处 + security_scan pre-push 钩子防新增；不做 filter-repo 重写（SHA 全改写/clone 分叉/GitHub fork 网络残留不可彻底清除）。"
evidence: "evidence://v1/e253003acbb83e654524405522f1c8b7261851503af00617e8b65ee108dd2379（2026-10-26 21:14 task_state 持久快照：敏感度分级扫描结论——真实密钥无/公网 IP 零命中/暴露=用户名 <user> 54 卡；当前树脱敏 14 卡 24 处+security_scan 钩子防线）；原始扫描命令回执已随 compaction 归档。"
tags: [security, git-history, p2-archived, user-decision, realtime_multimodal]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-27T22:29:52.163690+08:00"
updated_at: "2026-10-27T22:29:52.163690+08:00"
---

背景：2026-10-26 敏感度分级扫描（git 历史全树，2894beda7^ 口径）：真实密钥零命中（api key 命中仅为占位符 'x'/词面）、公网 IP 零命中（排除回环/内网/保留段）、实际暴露仅本机用户名 <user>（/Users/<user> 及 --Users-<user>- 变体，experiences/ 54 张卡；当前树已脱敏 14 卡 24 处 + security_scan 钩子防新增，已在 2894beda7 生效）。用户 GitHub 账户 deyi2026 本就公开。评估 filter-repo+force-push：需改写全部 SHA、所有 clone 分叉、GitHub fork/PR 网络中旧 commit 对象仍短期可达（彻底清除需 GitHub Support 人工处理）——代价远大于收益。用户 2026-10-27 22:27 确认选 A：挂 P2 收档，不做历史重写。收档口径：历史暴露物仅用户名，低优先已知项，不再处理；重开条件=用户名敏感度升级（与笔名/账户强绑定等）。同类事项默认处置：先做敏感度分级（密钥/IP/个人标识三级），仅真实密钥与凭证级暴露才考虑历史重写。