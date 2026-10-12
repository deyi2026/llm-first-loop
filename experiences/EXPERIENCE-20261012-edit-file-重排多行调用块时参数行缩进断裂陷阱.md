---
title: edit_file 重排多行调用块时参数行缩进断裂陷阱
scenario: "对 runner.py _worker() 内部 try 块做 edit_file：old_string 只含 `try: result = self._run_reserved_child(` 两行，new_string 在其外再包一层 try 并缩进首行——工具按字面替换，原调用的参数行（sid=sid 等十余行）不跟随缩进，产生语法破坏。py_compile 当场暴露。"
root_cause: ""
solution: 凡要给含多行调用的块整体加包装层（try/finally、with 等），old_string 必须完整覆盖到调用收尾括号为止（整块替换），不可只锚首两行；或分两步：先加外层骨架+占位，再整体替换内块。编辑后立即 py_compile 目标文件兜底。
evidence: "evidence://v1/22bae7d3920863512447033b918dcd04b5a4c9fb10813503a538d39b1d5c7e16（编辑后文件 1300-1339 参数行缩进断裂实测）；修复 diff evidence://v1/13814349fa3b5b253d6fe003aba23decd07e8f48667dd87f23209e1c952bf7e5；py_compile+pytest 全过 evidence://v1/58ed2f18a93d8bcf7e6ce43f5dc0e12950ad908a66baef9d7af004474de1af77"
tags: [edit_file, python, indentation, snapshot]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-12T06:44:28.011756+08:00"
updated_at: "2026-10-12T06:44:28.011756+08:00"
---

编辑链：read_file(snapshot=true) → edit_file(expected_snapshot_ref)。注意连续编辑同一文件时 expected_snapshot_ref 必须传上一次成功编辑返回的新 artifact ref，不能用旧 ref（报「snapshot 不属于当前工作区/路径」）。多行 old_string 之外新增悬挂块时，先 read_file 复核再整体替换。