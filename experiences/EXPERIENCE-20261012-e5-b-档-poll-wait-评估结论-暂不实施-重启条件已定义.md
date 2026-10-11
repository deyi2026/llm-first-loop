---
title: E5 B 档 poll_wait 评估结论：暂不实施，重启条件已定义
scenario: E5 wait 工具 B 档 poll_wait（等待期叠加对象状态轮询、条件满足提前唤醒）是否实施
root_cause: ""
solution: 评估后挂起：安全冲突（绕 fence 风险）+ 收益窄 + 无真实场景；出现真实案例再重启
evidence: "evidence://v1/a99328a5144ecf22e7a4374bf47f67e9d1f39fd15fd5368bd96b47be55c96864（wait.py 实现：零副作用只读原语）；E5 提案实测记录（child execute_command 被 run-lease fence 13/13+1/1 拒绝）"
tags: [E5, poll_wait, 演进评估, 挂起]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-12T07:14:13.554843+08:00"
updated_at: "2026-10-12T07:14:13.554843+08:00"
---

评估结论：暂不实施。理由（基于已核实代码事实）：
1. 安全边界冲突：wait 是零副作用只读原语；若 poll 谓词接受任意 shell 命令，等于借 wait 绕过 run-lease fence 对 child execute_command 的全量拒绝（E5 背景实测 13/13+1/1 拒绝），直接破坏已有安全边界。
2. 白名单谓词形态（file_exists/http_ok 类）收益窄：每种谓词需实现+测试+维护；http 引入网络出站面；模型退化路径 wait(120)+自查 已可用，B 档仅省一次空查。
3. 不服务主场景：E5 主场景是心跳降频（纯时间片），A 档已覆盖；"child 等外部事件"暂无真实案例。
重启条件：出现真实的"child 长等待外部事件"任务案例（如长任务子代理轮询构建完成标志），携具体场景重新提案。当前应优先完成 E5 预算缺陷修复（EVO-20261012-32e89b46）。