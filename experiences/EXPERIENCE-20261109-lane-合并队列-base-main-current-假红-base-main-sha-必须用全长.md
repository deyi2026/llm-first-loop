---
title: lane 合并队列 base_main_current 假红：base_main_sha 必须用全长 sha（短 sha 走字符串比较必挂）
scenario: lane_queue_submit 的 S0 机检 base_main_current 报失败，但 main 实际上没有前进（lane 就是基于当前 main head 建的）
root_cause: ""
solution: |
  base_main_sha 一律传全长 40 位 sha（lane_update 的 base_main_sha 也同步改全长），重发一次 submit；不要因为 FAIL 去 rebase 分支。
  当前性验证：先读 src/llm_loop/guard/lane_merge_queue.py（或 grep -rn "base_main_current" src/）确认比较仍是字符串相等而非 prefix 比较；复现：用 8 位短 sha 调 lane_queue_submit 应得 base_main_current=FAIL，换全长得 pass。
evidence: "14:43 用 base_main_sha=3171f1278 提交 → S0 base_main_current FAIL（entry_base 短 sha vs main_head 全 40 位字符串比较）；改用 3171f12786a35e4607263737c15b3b98c412a028 后四条机检全 pass（queue mq-0eed7777）。证据：evidence://v1/c0ee3970ba8a6a8e1a04d8d3f0ef92104b36f51c00c61d1c487cbbfb33097382（失败）、evidence://v1/fb1d5aa023d849b2469107d0215dfca215ea18b76a1b33f0fd2908125b9bfdee（通过）。"
tags: [lane, queue, sha, false-red]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-09T14:48:34.400711+08:00"
updated_at: "2026-11-09T14:48:34.400711+08:00"
---