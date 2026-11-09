---
title: 从上一班脚本批量改名时替换列表必须长模式在前：短模式先命中会让日期前缀错位并导致收口读不到回执
scenario: 从上一班脚本批量复制改名的批量替换顺序错误，导致回执文件名日期前缀错位（本班 2026-11-09 早班 d73）
root_cause: ""
solution: "批量替换列表里更长的模式排前面（先替 \"20261108-daily72\" 再替 \"daily72\"）；改完 grep 脚本里的输出文件名核对；收口前先 ls 实际落盘名与脚本期望名是否一致，不一致先改名。"
evidence: "本班收口时 scripts/_d73_closeout.py 抛 FileNotFoundError: .../receipts/20261108-daily73-public-verified.json；ls 显示实际落盘文件为 receipts/20261108-daily73-public-verified.json（日期前缀未替换）；改名 + sed 修正两处脚本后 closeout 通过"
tags: [脚本改名, 批量替换, 文件名, 收口核对]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-09T08:56:11.263519+08:00"
updated_at: "2026-11-09T08:56:11.263519+08:00"
---

场景：2026-11-09 早班 d73，从上一班（d72）的发布/验收脚本批量复制改名成 d73：用 sed 按替换列表依次替换（列表里有 ("daily72","daily73") 与 ("20261108-daily72","20261109-daily73") 两条）。因为 "daily72" 更短、先命中，"20261108-daily72-public-verified.json" 先被改成 "20261108-daily73-public-verified.json"，随后的长模式再也匹配不到 —— 结果回执落盘名带着前一天日期（20261108），收口脚本按预期名去找时直接 FileNotFoundError。

解法：批量替换列表里**更长的模式必须排在前面**（先 "20261108-daily72" 再 "daily72"）；替换后立刻 grep 输出文件名核对（`grep -n 'public-verified' 脚本.py`）；收口前先 `ls receipts/ | grep` 确认实际落盘名与脚本期望名一致，不一致先改名再跑收口。

适用边界：任何「从上一班产物复制脚本并改名」的场景都适用，不限于推广班次；含日期前缀的文件名尤其容易踩（日期与批次号是两段独立前缀）。