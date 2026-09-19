---
method_id: triage-terminal-ci-failures-and-reproduce-gate-script-locally-e85b4cc2167d
name: triage-terminal-ci-failures-and-reproduce-gate-script-locally
description: PR 出现红色 CI 检查时，先把检查分为终态 FAILURE（需行动）与 IN_PROGRESS（只需等待）。对终态失败拉一次失败日志：若日志只含泛化 banner（如 'gate: FAIL'）但暴露了检查是在已知 head SHA 上运行仓库本地脚本/命令，则停止反复过滤远程日志，改为在本地同一 commit 复跑该脚本取得具体违规项；再读检查器源码与一份已通过的同型工件推导其精确机械要求，做最小修复推送，并在新 head 上确认同名检查转绿后才回到等待其余门禁。用一次确定性本地复现替代反复拉取远程日志与猜测。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5adf278f-405b-44db-95e5-3d3b94e1b8d9:80:8473e9103e34ab06bfef
evidence_refs: learning:learn:20abd7b45922
created_at: 2026-09-19T11:09:57.092635+00:00
updated_at: 2026-09-19T11:09:57.092635+00:00
---
## Trigger
PR 的 CI 检查出现 FAILURE（尤其秒级完成的机械门禁），且失败日志被截断或只含泛化失败信息而没有具体违规项

## Discriminator
失败日志中可见检查实际执行的仓库本地脚本/命令行与 head SHA（例如 python scripts/check_X.py，且 checkout SHA 已打印），同时该检查状态为 COMPLETED+FAILURE 而非进行中——这两个当时已知事实共同把『等待变绿 / 反复过滤日志 / 猜测原因』缩成『本地确定性复现一次』

## Short path
- 用显式 --repo 取 PR 检查汇总；若 gh 无法解析 PR 号且存在多个 remote，先枚举 git remote 再逐个 GitHub remote 显式查询
- 把检查分为终态 FAILURE 与 IN_PROGRESS：只对终态失败行动，进行中的门禁只需定时等待
- 对每个终态失败拉一次 --log-failed，提取其中执行的脚本/命令行与 head SHA
- 若该命令是仓库本地脚本，则在本地同一 commit 复跑它，取得具体违规信息（缺什么工件、哪些路径不匹配）
- 读检查器源码 + 一份已通过的同类工件，按其声明的精确机械规则（如恰好一份清单且路径精确覆盖全部变更）做最小修复并推送
- 在新 head 上确认此前失败的同名检查报告 SUCCESS 后，才回到等待剩余门禁

## Stop conditions
- 本地复现已给出具体违规项且最小修复已推送
- 检查依赖 CI 专属环境（密钥、外部服务、e2e 浏览器）无法可信本地复现 → 改回远程日志与 artifact 分析
- 剩余检查均为非终态（IN_PROGRESS/QUEUED）→ 转为定时轮询等待，不再重复拉日志

## Verification
- 本地复现输出的失败 banner 与 CI 日志中的失败行一致
- 推送后新 head 上同名检查报告 SUCCESS，而不仅是 mergeStateStatus 变化
- 本地重跑检查脚本干净退出，确认满足其声明的精确规则（如路径覆盖完全一致）

## Counterexamples
- 失败日志本身已含完整 traceback/断言细节 → 直接读日志定位即可，本地复现无增量信息
- 失败依赖 CI 独有环境或外部服务（本地可能通过而 CI 失败）→ 本地复现不可信，应以远程日志/artifact 为准
- 疑似 flaky 的失败 → 先重跑该 job 观察是否自愈，而不是当作确定性门禁去修
- mergeStateStatus=BLOCKED 源于评审要求或分支保护策略而非检查脚本 → 无脚本可复现，应处理策略性原因
