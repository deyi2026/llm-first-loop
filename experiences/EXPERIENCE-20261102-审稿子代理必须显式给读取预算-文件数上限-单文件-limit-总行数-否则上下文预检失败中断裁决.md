---
title: 审稿子代理必须显式给读取预算（文件数上限+单文件 limit+总行数），否则上下文预检失败中断裁决
scenario: 给独立审稿子代理下达「读完这些文件全部核对」的宽指令，子代理连续读了 10 个文件、tokens_in 达 188K，触发运行时上下文预检失败并以 failed 中断，裁决只靠事后 agent_followup 续话才拿到，且续话产物含 1 项误报（声称正文出现实际不存在的数值）与 1 项真实阻断缺陷。
root_cause: 子代理继承父执行域，模型输入接近实际窗口时触发子代理上下文预检（自检上下文预算）并拒绝静默截断，直接以 failed 收口。宽范围审稿任务若不预设读取预算，很容易一次性把窗口耗尽。
solution: spawn 审稿子代理时在 task 里写明：①最多读 N 个文件；②单文件用 read_file 的 offset/limit 只读必要区间，不读整份大文件；③到预算即基于已读内容下结论，未实际核对的写「未核对」而不猜；④输出字数上限。窄复审用同样的更小预算。
evidence: docs/promotion/STATUS-20261102-daily52.md 第六节（subagent_85187cb4dc06 失败实录：rounds=10 tools=22 tokens_in=188270；其续话产出 P0-1 误报「正文出现约 30%」，grep 复核正文与台账均无该值）；后续 subagent_e33b95e99a23（带读取预算）跑完 16 轮出 REVISE、subagent_6eef0ce8311d（定点 4 项、200 行内）出 PASS
tags: [spawn_subagent, 审稿, 上下文预算, 独立复核]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-02T08:43:53.994533+08:00"
updated_at: "2026-11-02T08:43:53.994533+08:00"
---