---
title: SWE 评测成果先导出再清理临时目录（避免 patch 永久丢失）
scenario: 完成阶段性任务（SWE 评测/实验/修复）后需要清理临时环境释放空间时。
root_cause: 清理环境（rm -rf）发生在导出成果之前；/tmp 目录无版本控制，删除即永久丢失。
solution: 清理铁律：先导出成果再清理环境。① 任务完成立即导出可复用产物（git diff patch、predictions.jsonl、结果报告）到持久位置；② 确认导出完整（文件非空、可反打验证）后才 rm；③ 清理前检查 git status/diff 非空即先导出。教训：pytest 19 实例 patch 永久丢失。
evidence: 2026-08-17 SWE-bench 测试：pytest 19 实例完成 35/35 后清理 /tmp/swe_instances 释放 1.1G，随后用户要求导出标准 predictions.jsonl——pytest 实例目录已删，patch 无法导出（git diff 丢失），仅 pylint 10 实例可导出。
tags: [成果导出, 清理顺序, SWE-bench, 数据保留]
source: {}
status: active
created_at: "2026-08-17T22:53:35.899336+08:00"
updated_at: "2026-08-17T22:53:35.899336+08:00"
---