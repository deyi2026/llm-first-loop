---
title: 交付文档写本机绝对路径会被 pre-commit 安全扫描拦截
scenario: 把 live 实测回执写进 docs/DELIVERY-20261030-write-scope-p1a-rollout.md §8.7 时原样引用了 `/Users/<user>/<repo>/…` 形态的本机绝对路径，git commit 被 pre-commit 钩子以「疑似本机凭据/路径泄露」硬拦截（本卡自身也按此体例脱敏后才可入库）。
root_cause: "仓库 pre-commit 扫描把 `/Users/[A-Za-z0-9_]+/` 形态判为敏感本机路径并阻断提交；文档既有体例是用 `…/` 省略（§8.3 即如此），新写内容未沿用。"
solution: 交付文档中的本机路径统一写 `…/…` 或 `<工作区上一级目录>/…`，与既有体例一致；若确需原样路径，先确认扫描脚本的 _ALLOWLIST 是否已登记该形态（本次未改扫描脚本，也未用豁免绕过扫描）。
evidence: "evidence://v1/cc8a79b7582ef698e41537cac00a15ff2dc9a084099608f52b5b2a9b4bfdedd1（拦截回执，pattern=/Users/[A-Za-z0-9_]+/）；改写为省略形式后同一命令提交成功（提交 66950cd09，见 evidence://v1/e066a1a286f54553c4376244e3f90c78e6c3e52f3b32ec139ea32a51cddd645f）"
tags: [docs, git-hook, delivery]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T23:39:20.757657+08:00"
updated_at: "2026-10-30T23:39:20.757657+08:00"
---