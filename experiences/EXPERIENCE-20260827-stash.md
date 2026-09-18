---
title: 等值单源化重构的隐性契约陷阱 + stash 分组归因法
scenario: 等值重构（委托合并/单源化）后的全量测试回归定位；测试构造参数修正的验证纪律
root_cause: "①等值重构改变了隐性的\"属性访问面\"契约——测试桩按旧路径最小依赖面构造；②构造参数基于纸面推导（系数假设 0.6，实际 0.5）且未实测就进 diff"
solution: 等值重构时统一防御式属性访问（getattr fail-open）；构造类测试修正必须当场跑过；归因用 git stash 分组对照（只 stash 嫌疑 src、保留测试修改）3 分钟定位
evidence: ""
tags: [refactor, equivalence, test-stub-contract, stash-bisection, fail-open]
source: {}
status: active
created_at: "2026-08-27T18:37:09.132416+08:00"
updated_at: "2026-08-27T18:37:09.132416+08:00"
---

背景：routing.py 存在 _effective_history_budget（旧，不触 self.runtime）与 _effective_history_budget_detail（访问 self.runtime）两份等值实现。T5 单源化为一个 resolver 后两者委托同一实现，数值等值，但 test_model_pool_per_model 的 _Engine 桩（最小依赖面）因缺 runtime 属性 AttributeError。修复：self.runtime → getattr(self, "runtime", None)（fail-open 风格）。同类：早前批次把测试构造 262→300 按 kept 系数 0.6 推导，实测 0.5（320K×0.5/855≈187 组），n=300 实际归档 43 组 drop 13.9% 越界，且修正从未跑过就留在 worktree——stash 分组法（只 stash 嫌疑 src 保留测试修正）3 分钟定位归属。规避：①等值重构前 grep 两实现的所有 self.<attr> 访问差异，防御式风格统一；②构造边界类测试修正必须当场定向跑过再进 diff；③归因用 git stash push <files> 分组对照，勿凭直觉归因。