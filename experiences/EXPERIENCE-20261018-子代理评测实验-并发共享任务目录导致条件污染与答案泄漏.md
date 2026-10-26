---
title: 子代理评测实验：并发共享任务目录导致条件污染与答案泄漏
scenario: "跑多条件 agent 对比实验（如 A/B/C 三组并行跑同一任务）时，多个 run 共享同一个任务工作目录，各自读写中间产物文件。症状：①后跑的条件能看到先跑条件留下的研判文件，条件隔离失效；②答案键 answer.md 与被评测任务放在同一目录，跑手可能直接读到答案；③并发启动多个 dsh 抢同一 session 锁，产出 `[dsh-repeat-stop]` 空产物；④模型把结果写进文件而非 stdout，采集脚本只收 stdout 就拿到空内容。"
root_cause: "把\"任务定义目录\"直接当作\"每个 run 的工作目录\"，导致跨条件共享可变状态；并发与写文件行为进一步放大了干扰。"
solution: |
  1) **沙箱隔离**：每个 run 用独立目录 `sandboxes/<task>-<cond>/`，只拷 fixture，**绝不拷 answer.md**；答案键另存他处，仅 grader 可见。
  2) **串行执行**：多条件改为串行，避免并发抢同一 dsh session 锁导致 repeat-stop。
  3) **强制 stdout**：提示词末尾追加输出纪律——"不要创建/写入/执行任何文件，只只读；结果直接作为回复正文输出"。
  4) **产物有效性校验**：按文件数字数统计"完成步数"会漏判，必须校验内容（长度阈值 + repeat-stop 特征串检测）。
  5) 场景与答案分离存放，评测目录内不含任何答案信息。
evidence: 首轮 6 次运行出现 3 个 repeat-stop 空产物，tasks/ 下发现跨条件产物 step2-assessment.md、step3/candidate/core.py、verify/ 等；grep 确认多个 run 的 gate/execute 步引用了这些外部产物。
tags: [实验设计, 子代理评测, 条件隔离, 沙箱, 并发, dsh]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-18T01:51:14.179575+08:00"
updated_at: "2026-10-18T01:51:14.179575+08:00"
---