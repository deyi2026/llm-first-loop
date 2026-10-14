---
title: learning-channel 观测能力的只读派生视图实现模式（usage_net）
scenario: "为 LFL 运行时增加\"使用净分\"派生观测（search_records 命中行注记 + 生命周期工具回执阈值提醒），数据源是两侧既有的 record_use usage.jsonl 账本。"
root_cause: ""
solution: "纯派生模块 + 双侧 store 只读方法 + 既有聚合层接入，全程 fail-open；D3 锚点用账本条目内嵌的\"声明时 status\"与当前 status 尾段一致回溯，零写路径变更、零 schema 迁移。"
evidence: "tests/unit/test_usage_net.py 11 passed（evidence://v1/4ea1918650ffdc544a06fefb8e7902106173d8846221271ec1be8eae1e210cbb）；受影响 6 套件 107 passed（evidence://v1/33e07e148514e94ff86b43e23fd26d90d3ae7789825aa4ac441473cc6891d91d）；git commit 2fca1cba3"
tags: [learning-channel, derived-view, usage-ledger, evolution]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T08:51:23.174605+08:00"
updated_at: "2026-10-14T08:51:23.174605+08:00"
---

EVO-20261014-7299aec2 落地模式（git 2fca1cba3）：需要跨 method/experience 的运行时观测能力时，不建平行账本，在两侧 store 加只读 usage_net()，逻辑放纯模块（llm_loop/usage_net.py）；聚合点复用既有 card_age 注记层（search._annotate_usage + tools_status._usage_net_part），回执附加走 fail-open try/except，派生视图异常只降级不加字段。D3 锚点技巧：账本条目若内嵌声明时 status（method 键 method_status / experience 键 status），用"尾段一致回溯"实现 lifecycle 重锚，零 schema 变更。