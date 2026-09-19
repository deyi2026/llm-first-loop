---
method_id: consume-failure-scope-before-broad-fetch-f6c25a77e480
name: consume-failure-scope-before-broad-fetch
description: 工具或 CI 的失败输出本身通常已指明确切作用单元：无效 workdir 报错指向 pwd、gh pr checks 已把'哪些检查红'缩为带 ID 的失败 job 集合、日志截断(complete:false)说明需过滤而非重取。本 episode 却对同一 job 无过滤地重复 gh run view 并做 80 字符窗口 hydration，才拿到本可一次 grep 命中的 ##[error] 行。方法：每个失败事件先消费其内嵌范围，做一次定向查询（按 job 过滤错误行 / 本地复现工具错误）；查空或无法解释时才扩大范围。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:799:1758d3811e58433620d3
evidence_refs: learning:learn:c89ccef7e75a
created_at: 2026-09-18T01:25:04.367270+00:00
updated_at: 2026-09-18T01:25:04.367270+00:00
---
## Trigger
任一工具/CI/门禁返回失败或截断结果，且失败信息已自带定位线索（点名路径、失败 job ID、##[error]/FAIL 标记、错误计数、complete:false 截断元数据），需要定位根因或恢复现场

## Discriminator
当时已知：(a) workdir 报错明确点名无效路径 /workspace，pwd 输出已给出真实仓库且含 .git；(b) gh pr checks 28 已把失败缩为恰好 2 个唯一 job 及其 ID，其余 pass/skip；(c) 首次 gh run view 输出 40 行即截断且 hydration 仅回 80 字符(complete:false)，证明日志量远超单次读取上限，应服务端过滤而非重复全量取或逐页取

## Short path
- 由失败自身指针导出下一步而非平行枚举：workdir 报错 -> pwd + git remote -v 定位仓库（未知量：当前在哪个 repo；不做 find / 全盘扫描）
- gh pr checks <PR> 一次取得失败 job 集合与 ID（未知量：哪些门禁红）
- 每个失败 job 只做一次带过滤的提取：gh run view --job <id> --log-failed | grep -E '##\[error\]|FAIL|Found [0-9]+ errors|Traceback|error:' | head -40（未知量：该 job 根因）
- 工具类错误（ruff/pytest/pyright）改本地复现取 file:line 与完整错误列表，不再读远端日志（未知量：13 个 ruff 错误的具体位置）
- 自定义门禁断言只 grep 断言相关脚本段（MANIFEST_PREFIX/coverage）理解语义，不读全脚本、不扫全目录
- 每个失败 job 归因到单一原因后立即停止日志读取，进入修复或等待唤醒

## Stop conditions
- 每个失败 job 都有一条来自 ##[error]/FAIL/工具错误行的明确根因
- 本地复现错误集合与 CI 报告完全一致（如 ruff Found 13 == 本地 13）
- 新增日志/目录读取不再改变任何下一步行动

## Verification
- 过滤出的错误行的 step 名与该 job 的失败 step 匹配
- 本地复现错误数与规则集合 == CI 报告（数量与规则码一致）
- 归因能解释该 job 全部错误行，而不只是第一行

## Counterexamples
- flaky/基础设施失败（runner 超时、网络 5xx）：本地复现不成立，需完整日志或重跑验证，不能按'错误行=根因'收口
- 仅 CI 环境可复现的失败（密钥、矩阵 Python 版本、架构差异）：本地工具全绿但 CI 红，必须查 CI 环境而非本地复现
- 根因藏在更早的通过 step（静默 warning 级联）：只 grep ##[error] 会漏，需回看失败 step 之前的输出
- 日志总量很小且仅单 job：直接读全量即可，过滤是多余开销
- grep 无命中时换参数反复重发同一命令：应回退为读完整失败 step，而不是继续窄过滤枚举
