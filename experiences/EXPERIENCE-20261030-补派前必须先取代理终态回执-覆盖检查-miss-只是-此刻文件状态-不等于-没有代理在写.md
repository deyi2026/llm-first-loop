---
title: 补派前必须先取代理终态回执：覆盖检查 MISS 只是「此刻文件状态」，不等于「没有代理在写」
scenario: 用文件覆盖检查（某卡对应的回执文件是否存在）判断「这张卡还没人做」，据此给同一张卡补派第二个评审代理——但第一个代理仍在运行、只是尚未落盘。结果同一张卡产出两份回执，harness 以 duplicate_verdict_for_ref 拒收合并。
root_cause: ""
solution: 1) 「覆盖检查 MISS」只代表此刻文件状态，不等于「没有代理在写」；补派前必须先取该代理的终态回执（subagent_result），确认它已结算且不会再写同一张卡。2) 若已补派造成双份：只落一条回执（保留已落库的那条），删除冗余评审文件，重跑 harness 确认恢复 problems=0，冗余件留档备查。3) 通用形态：把「缺输出」当作「任务未开始」是典型的时序误判——代理的落盘时刻晚于调度时刻，缺输出往往只是还没到。
evidence: "本轮 harness 两次回执：rc=2 / {\"call_count\": 18, \"problems\": [{\"method_ref\": \"method:verify-sink-and-background-before-heavy-env-installs-f23d33455b3e\", \"problem\": \"duplicate_verdict_for_ref\"}]} → 清理后 rc=0 / 18 calls / 0 problems；落库核验 18/18 qualification_episode_ref 绑定 episode:cab051cc-...:1674:4b86ae817df9ad27bb35（每卡 1 条）；时间线：12:05:17 覆盖检查 MISS → 12:05:23 补派 → 12:05:59 首个代理落盘 05.json；治理记录写入 docs/governance/card-lifecycle.md（commit 48f9dc003）"
tags: [subagent, dispatch, race, duplicate, coverage-check, gate]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T12:15:42.238765+08:00"
updated_at: "2026-10-30T12:15:42.238765+08:00"
---