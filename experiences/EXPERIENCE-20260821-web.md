---
title: 数据文件打标/写入后必须磁盘重载验证存活（web 进程旧内存态会回滚裸写）
scenario: "P0-2 记忆分级两次失败：打标脚本输出 changed=11/session=13（写入当刻成功），但几分钟后审查方查磁盘只有 2 条 session——裸写 index.json 被 web 进程（持有旧内存态）任一记忆写入触发 save 时用旧态覆盖回滚。汇报\"已完成\"前必须验证长期存活，不能只信写入回执。"
root_cause: 长驻进程（web/feishu）在内存持有旧态数据，进程间无共享锁的裸文件写会被进程自身后续 save 覆盖（lost update）；记忆库 MemoryStore 有 _merge_remote_changes 写前合并，但裸写 json.dump 不走该路径。
solution: 改数据文件（尤其有长驻进程共享的：memory/index.json、sessions、schedule.json 等）遵循三步闭环：① 写前备份（cp .bak-时间戳）；② 写入后立即磁盘重载（重新 open 读，确认新值在盘）；③ 隔一段时间/下次轮询再重载一次确认未被回滚。若被回滚：要么停写进程后写再重启加载，要么经进程共享的存储 API（如 MemoryStore._merge_remote_changes 写前合并）而非裸写文件。汇报完成时附磁盘证据（路径+条目数+值），不只报工具回执。
evidence: "2026-08-20 P0-2 两次实证：备份 vs 当前 scope 改动数=0（打标未存活），mtime 晚于打标时刻证明被并发覆盖；决策文档 docs/DECISION-memory-scope-standard.md §6 记录\"裸写文件+不重启=必然被旧内存态覆盖（已两次实证）\"。"
tags: [data-integrity, concurrent-write, persistence-verification, memory-store]
source: {}
status: active
created_at: "2026-08-21T00:25:01.441449+08:00"
updated_at: "2026-08-21T00:25:01.441449+08:00"
---