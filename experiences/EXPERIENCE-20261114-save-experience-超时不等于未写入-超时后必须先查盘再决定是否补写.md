---
title: save_experience 超时不等于未写入——超时后必须先查盘再决定是否补写
scenario: 本轮连续两次 save_experience 报「超过 60s 未完成」超时，我据此判定「经验卡未落盘」，又按同一教训手写了第三张卡。结果：同一教训出现 3 张 status: active 的近似重复记录，被独立审查判 REVISE（P0=0 P1=0 P2=5，5 条 P2 全部指向这批卡），额外经历一轮返工收敛。
root_cause: 把工具回执超时当作写入失败，未做落盘核验就采取补写动作；而手写补写前没有先确认不存在同 stem/同主题卡
solution: save_experience 超时后，先用 ls / grep 核验目标目录是否已落盘，确认真未落盘才补写；手写补写前必须再查一次同 stem 卡是否存在，否则不写。写完立刻统计该主题下的 status 分布，确保同一教训只有 1 张 active、其余走 status: superseded + superseded_by 链。当前性验证：复现 —— 执行 ls experiences/EXPERIENCE-20261114-知识卡生成器*.md | wc -l 应为 3，且 grep -h '^status:' experiences/EXPERIENCE-20261114-知识卡生成器*.md | sort | uniq -c 应为 1 active + 2 superseded；核验必须用文件名模式而非全文 grep——全文 grep 会匹配到本卡内引用的关键词，把无关卡误计为重复
evidence: "evidence://v1/195856f953363e7abfac0fda2635e0d59dc93f51cb35b2d13a8ea91ce1d52f22; evidence://v1/c10ccf2b83beccdf59f9c87f7cf094c0481cdcb764bd11417aee07267d47d848"
tags: [knowledge-pipeline, tool-semantics, self-review]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-14T14:05:00+08:00"
updated_at: "2026-11-14T14:05:00+08:00"
---
