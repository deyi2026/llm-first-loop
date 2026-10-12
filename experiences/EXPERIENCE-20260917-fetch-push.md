---
title: 长部署会话未 fetch 远端导致分叉发现过晚（push 才暴露）
scenario: 镜像工作区长会话持续推进部署线（managed_service_deployment 代数推进）期间，远端 main 被另一操作通道（MCP Console）独立推进；本地长时间不 fetch，分叉发现过晚
root_cause: ""
solution: 部署会话开始先 fetch 远端并对比分叉；发现分叉立即停止推进，用只读 API 审计对方提交，交用户裁决整合顺序；永不 force push
evidence: "2026-09-17 22:31 push non-FF 拒绝（job-71c327a8）；22:33-35 fetch curl 28 失败；API 只读通道取得远端头 ddd108a2 及其 submission 文档（docs/governance/submissions/20260917-cache-fold-corrective-main-v2.json）；本地 main=d3f6b150，merge-base=3eaae8f6"
tags: [git, fetch-discipline, divergence, managed-service, remote-sync]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-17T22:36:10.519040+08:00"
updated_at: "2026-09-17T22:36:10.519040+08:00"
---

现象：本地镜像推进了 10 代部署（gen1→gen10，15 个提交）数小时未 fetch 远端；push 时才以 non-FF 拒绝暴露分叉——远端 main 已被 MCP Console 推送独立裁决线（T0 底座 + v2 纠正，+145/−7813）。此时本地 git 网络恰好中断（curl 28），连"看清对方"都要靠只读 API。
代价：双线各自累积大量工作后才相遇，重叠区（config.py/resolver.py）需要按 ownership 三方裁决，整合成本远高于早发现。
做法：每个部署会话开始时先 git fetch <remote> main 并核对 lfl/main 与本地 main 是否分叉；分叉即停，先审计对方提交（API 只读通道可作网络降级路径：api.github.com/repos/<org>/<repo>/commits/<sha>），由用户裁决整合顺序。禁止 force push 掩盖分叉。