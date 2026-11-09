---
title: 口径词不能替换——Impact-F1 margin ≠「漏判的代价」、solve rate ≠「做不完整」、CUPMem 复现版本 ≠「作者对 CUPMem 的复现版本」
scenario: 对外稿把论文指标用自己的话概括时，最容易被审稿人抓到的是「换个词说同一个量」：把 Impact-F1 margin 说成「漏判的代价」（口径换成了漏判）、把 solve rate 说成「做不完整」（摘要没给部分完成数据）、把「相对 CUPMem 复现版本」写成「CUPMem 复现版本」（读者会读成本文复现了 CUPMem）。本班 d71 三处全被独立审稿人抓到。
root_cause: ""
solution: 凡涉及论文指标的句子，先照抄摘要的指标名与限定语，再补自己的解读，并单独成句标明是解读（如「这是本文把几篇论文的读数串起来后的解读，不是任何一篇论文的结论」）；涉及「谁做的复现」必须写出主语（作者对 CUPMem 的复现版本）；摘要没给的归类（整体产出/能力）一律不写。
evidence: d71 第二轮审稿 subagent_d36d34cba2a3 报 F4（P1，Impact-F1 margin 被写成「漏判的代价」「漏判 margin」）、F5（P2，整体产出/能力归类非摘要所给）、F2（contract_changes 应为 contract_hit）；第四轮 subagent_5709a1abf7e4 报 D2（P2，「CUPMem 复现版本」易被读成本文复现）。全部修订后第五轮 subagent_6e51eff1b43d 判 PASS（p0=0 p1=0 p2=0）。
tags: [promotion, paper, wording, review]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-08T13:48:11.113139+08:00"
updated_at: "2026-11-08T13:48:11.113139+08:00"
---