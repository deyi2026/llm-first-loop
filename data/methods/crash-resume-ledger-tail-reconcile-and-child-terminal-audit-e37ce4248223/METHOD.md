---
method_id: crash-resume-ledger-tail-reconcile-and-child-terminal-audit-e37ce4248223
name: crash-resume-ledger-tail-reconcile-and-child-terminal-audit
description: 会话出错后用户要求『从保存的会话与日志找回并继续』，且存在持久账本（活动 goal/checkpoint、append-only evidence/event 流、VCS 工作树）时：按权威顺序重建状态——goal checkpoints → 事件流末尾 → 水合末尾 2-3 条 evidence → 用已知唯一文件名一条 find 定位工作副本 → git status 对账，而不是 ls 家目录逐层枚举。关键新判别：证据流末尾的 child/runtime_snapshot 条目点名中断瞬间的在飞异步工作，其终态（本集 cancelled、rounds=18 无产出）是『丢失了什么』的唯一账本记录，docs 与 git 都看不见；git+文档对账得出『已落盘』，子代理终态得出『已丢失』，差集即续作清单。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:881d9c3f-2c5a-47a8-b605-9596af0a61b1:533:9489f59d2cf250b6e127
evidence_refs: learning:learn:05d95a7e2013
created_at: 2026-10-17T10:47:50.314647+08:00
updated_at: 2026-10-17T10:47:50.314647+08:00
---
## Trigger
会话崩溃/出错后用户要求从持久化会话与日志恢复并继续，且系统存在活动 goal 与 checkpoint 登记、append-only evidence/event 流、版本库工作树，中断前通常还 spawn 过子代理或存在等待中的异步任务

## Discriminator
中断时刻已知的三类事实足以收敛搜索：① goal checkpoint 已写出停点文档相对路径与新模块文件名，可直接从文件系统根 find 定位工作副本，无需目录枚举；② evidence 流末尾时间戳=精确断点，其中 child running + wait elapsed 条目指示在飞异步工作；③ git 工作树（而非账本自报）证明哪些改动已落盘。三者交叉即可唯一确定『重做什么』

## Short path
- 查 goal 与 checkpoints：拿到目标、最近停点、停点文档相对路径与自报进度（未知量：任务是什么、停在哪）
- 读 event/evidence 流末尾：确定最后已决定动作与精确中断时间戳（未知量：断点时刻在做什么）
- 水合末尾 2-3 条 evidence：还原断点瞬间观测——子代理 running、wait elapsed、探针输出（未知量：什么还在飞）
- 逐个查询在飞子代理/异步任务终态：cancelled/finished + rounds/tools/产出，即丢失工作清单（未知量：丢失了什么——此项 docs 与 git 均不可见）
- 用 checkpoint/事件流中已出现的唯一文件名（新增模块、设计文档名）从文件系统根一条 find 定位工作副本；命中后 git status/diff 列未提交/未跟踪改动
- 对账：git 证实『已落盘』，子代理终态证实『已丢失』，差集=续作项；只重做差集（本集=重跑被取消的独立复审），完成后续作并同步停点文档状态头

## Stop conditions
- goal 自报状态、git 工作树、各在飞子代理终态三方对账一致，且丢失差集已列举为有限明确清单
- 不再为可从账本/VCS 自查的事实向用户提问或做宽枚举

## Verification
- 续作收尾时回看：实际重做项是否恰等于子代理终态揭示的丢失项，无凭空扩大、无遗漏
- 恢复结论与停点文档自写状态头（若有恢复入口节）一致；矛盾时以 VCS+终态为准并回写修正
- 恢复阶段命令数显著少于逐目录枚举路径（理想 ≤6 条定位+对账命令）

## Counterexamples
- 无持久账本、无异步子任务的普通聊天中断：直接读会话转录续读即可，本方法不适用
- 中断时无任何在飞子代理/等待：终态审计为空操作，方法退化为『停点文档+git 对账』，与既有 resume-continuation 方法重合
- 账本自报与 git 明显矛盾（登记已完成但工作树大片未提交/未跟踪）：以工作树为真值重建，不沿过期账本继续
- 账本中不存在唯一文件名（全新工作区/未命名产物）：才需要目录级或项目级 broad discovery
