---
method_id: read-entity-state-via-code-defined-store-api-fa83570ec780
name: read-entity-state-via-code-defined-store-api
description: 给出登记/状态流转类 CLI 命令前，沿代码自身链条取事实：命令 handler 引用的 store 类，其构造函数定义权威数据路径，其读方法（如 list()）给出实体当前状态。用该 API 确认状态，而不是猜存储目录、全盘 find（本例因此超时一次）、或手工解析 append-only JSONL（同 ID 多条记录互相矛盾，本例两条建议各解析出两种状态）。最后验证命令入口在目标环境真实存在（console script 缺失则 python -m + PYTHONPATH），再交出完整命令、预期回执与登记后核验。可把本例 21 次工具调用缩到约 5-6 次。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:1378:0b3bf821447af9c7976a
evidence_refs: learning:learn:b7d11835e8ca
created_at: 2026-10-18T10:25:37.407397+08:00
updated_at: 2026-10-18T10:25:37.407397+08:00
---
## Trigger
需要给出对持久化实体（工单/演进建议/任务）执行登记或状态流转的完整命令，须先确认该实体当前状态与数据位置；或状态查询返回空、或原始数据文件出现同 ID 多条矛盾记录时。

## Discriminator
已读过的 handler 源码明确引用具名 store 类与模块（如 engine.correction_ctx.evolution_store）；该类构造函数逐字给出存储路径、方法清单给出规范读 API——查数据前先读类定义即可消除路径猜测。同 ID 在原始文件中出现多条不同 status 是 append-only 日志的直接证据，当前状态必须以读 API 的聚合结果为准。

## Short path
- 从命令关键词 grep 到子命令分发与用法串，锁定参数契约（如 evolve-complete <id> "<说明>"）
- 沿 handler 引用读 store 类定义：构造函数得权威存储路径、方法清单得读 API；不猜目录、不做全盘 find
- 用 store 读 API（如 list()）查目标 ID 当前状态；若原始 JSONL 同 ID 多条矛盾，不再重复解析文件
- 确认实体确为待登记态（如 accepted 且 executed_at 为空）后，验证调用入口：console script 是否安装、python -m 与包解析是否指向正确源码副本
- 输出完整命令 + 预期回执 + 登记后核验命令 + 已知限制（幂等性、写死字段），停止扩展发现

## Stop conditions
- store 读 API 已给出目标实体唯一且无矛盾的状态
- 命令入口已验证可达（脚本存在，或 python -m 解析到正确源码副本）
- 完整命令与登记后核验方式已交付用户

## Verification
- 数据路径与 store 类构造函数定义逐字一致，而非猜测或目录枚举所得
- 实体状态以读 API 输出为准；与原始文件行冲突时记录差异并声明以 API 为准
- 给出的命令按原样在干净 shell 可执行：cd 路径、解释器、PYTHONPATH 均真实存在

## Counterexamples
- 存储是单值快照（每实体一条或整个文件即状态）→ 直接读文件即可，无需实例化领域类
- 用户只要命令语法、不涉及具体实体状态，且用法串已从 handler 获得 → 直接给用法并停止
- 领域类无可用读 API、必须离线解析 → 按时间戳/行序取该 ID 最新记录并显式声明该假设
- store 是外部服务（HTTP/DB），本地源码不含路径定义 → 改查配置/连接串而非构造函数
- handler 已明确打印环境前置失败（如 EVOLVE_ENABLED=0）→ 先满足前置条件，而非更换读取方式
