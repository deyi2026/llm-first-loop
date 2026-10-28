---
method_id: locate-authoritative-record-via-handler-store-code-c1394db56200
name: locate-authoritative-record-via-handler-store-code
description: 当用户问『我之前的操作（审批/提交/状态变更）是否已被持久化记录、现在什么状态』且该操作由本地代码库中的处理函数完成时，不要按目录名/通配符猜存储位置再逐个 grep。先用作用域受限的 grep 定位处理函数，从签名/函数体确认记录权威对象（store/repository），再由该类定义查出持久化文件/表，最后只在权威位置查那条记录 ID。本集先 ls data/*evolution* 宽枚举、grep data/evolution（空）、ls 两次、多绕三步后才由 EvolutionStore.__init__ 找到 data/audit/evolution_suggestions.jsonl，一条 grep 即得答案。
status: active
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:1211:1579326f1e74f40af147
evidence_refs: learning:learn:e5d89ff484f2
created_at: 2026-10-18T01:25:41.989135+08:00
updated_at: 2026-10-18T23:33:18.827177+08:00
---
## Trigger
用户询问某次已执行操作（审批/提交/登记/状态变更）是否被记录、当前状态如何；操作经仓库内代码处理；持久化位置未被用户或文档直接给出。

## Discriminator
处理函数签名/函数体在目录枚举之前就已可见地显示记录权威是注入的 store 对象（如 approve(store, evo_id) 内部走 _find(store,...)/store.review(...)）——这条 handler→store 因果边可把『记录在哪』从整个 data/ 目录缩到 store 类的持久化路径这一个未知量。

## Short path
- 作用域受限 grep 定位操作处理函数（如 def approve 于 src/ 下），读签名与函数体，确认记录权威对象是 store 及关键字段（status/时间戳/override 标志）
- 在 src 内 grep 该 store 类定义或其文件名常量（如 evolution_suggestions.jsonl），得到持久化路径（audit_dir/<file>），必要时一次 ls 确认部署路径
- 只在权威文件中 grep 该记录 ID，取 status/reviewed_at/human_exec_override，直接回答『是否已记录、要不要重做』
- 若需给出收口建议，再读对应状态转移函数（manual_complete/maybe_auto_execute）确认可达路径；从权威文件取到所需事实即停止

## Stop conditions
- 已从权威持久化文件取到该记录当前状态与关键标志（status、reviewed_at、override 布尔）
- 『是否需要重新提交/补操作』的判断已由处理函数与转移函数源码支撑

## Verification
- 记录 ID 与用户声称的操作一致，时间戳落在其声称的操作窗口内
- 结论中的状态机分支（如 level==0 且无 override 则等待人工）能在具体源码行号对应

## Counterexamples
- 存储位置已由用户/文档/上文明确给出（如直接被告知查某 jsonl 或 DB 表）——直接查该位置，先读代码反而是绕路
- 记录由外部系统持有（第三方审批平台、远端服务），本地代码无持久化路径——代码推导断裂，只能按已知日志/接口查询
- 询问的是进程内瞬态状态（内存锁、当前会话）而非持久化记录——store 持久化路径无关，应查运行时接口
