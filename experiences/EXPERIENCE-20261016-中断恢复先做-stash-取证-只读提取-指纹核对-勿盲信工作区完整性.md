---
title: 中断恢复先做 stash 取证：只读提取+指纹核对，勿盲信工作区完整性
scenario: "会话中断恢复后进入编码任务：工作区多个 src/tests 文件\"失踪\"（仅剩 __pycache__），任务书描述与实际树状态不符。"
root_cause: "上 run 在中断前为缩准入材料执行了 stash，运行时未在恢复路径上提示 stash 存在，造成\"文件消失\"假象；中断连带取消的子代理只完成了测试侧修改。"
solution: "恢复现场时固定加一步 stash 取证：git stash list 看条目时间戳是否落在中断窗口内；恢复用 git show stash@{N}:<path> > <path> 只读提取（不 pop/apply，不改 index/HEAD），并逐文件与审查回执指纹（sha256）比对后再采信；同时用 shasum 核对\"半成品\"边界（哪些文件被中断代理改过、哪些未改）。"
evidence: "git stash list 时间戳 2026-10-15 22:39:18 与上 run execute_command 回执时间吻合；恢复后 shasum 与 r1 回执指纹比对（settlement.py=b87c27d9…、test_settlement_receipts.py=d9e24f64…、test_search_feedback_reflow.py=02f64b8c… 逐字节一致）；修复后守卫 30/30、全量门 exit=0。"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-16T00:09:25.692297+08:00"
updated_at: "2026-10-16T00:09:25.692297+08:00"
---