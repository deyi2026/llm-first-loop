---
title: event_stream 用 session id 作 query 会漏检目标会话动作，误判停滞
scenario: 多会话并行时判断另一个 LFL 会话是否停滞/死亡，用 event_stream 查询其动作。
root_cause: ""
solution: "event_stream 的 query 是内容文本匹配：用 session id 作查询词只能命中内容里引用了该字符串的事件（如他人查询），会漏检目标会话自身的动作，造成\"停滞\"假象。判断会话活跃度必须用宽内容词（如仓库名\"StateBraid\"、工具名）+ since 时间窗 + limit 拉全量浏览；交叉证据用 subagent_topology 看其子代理 uncollected 状态、git reflog 看本地仓库最近操作时间戳。勿凭单一空查询结果判定死亡并接管。"
evidence: "event_stream 23:17 用 query=\"StateBraid\" 重查命中 826dee73 23:07-23:13 密集动作；gate 阻断回执\"不存在覆盖当前产物、目标及父会话的有效独立审查资格\"；重算 identity=9617d50a ≠ 冻结 3ea21e6c；git reflog 显示 23:12:32 rebase finish。"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-22T23:18:44.129595+08:00"
updated_at: "2026-10-22T23:18:44.129595+08:00"
---

误判案例：2026-10-22 22:58-23:07，用 event_stream(query="826dee73-c003-...") 查某会话死活返回空，误判其停滞并接管另一会话的 git push 任务。实际对方全程活跃（修复代码+rebase），只是其动作事件内容不含 session id 字符串。后被 Rule-28 gate 的 candidate sha drift-check 拦截，零写入。