---
method_id: dup-forensics-volatile-field-identity-plus-copy-lineage-2e19786207b7
name: dup-forensics-volatile-field-identity-plus-copy-lineage
description: 排查跨实体记录重复（同一 id/事件/行在多个 session 出现）时，先用重复对的易变字段（时间戳、运行时 id）是否逐字一致对机制空间做二分：逐字一致 ⇒ 物理字节复制（fork/clone/migrate/backup 恢复）；存在差异 ⇒ 重发/重放/并发再生成。随后只审计执行字节级复制的代码路径，并用谱系关联（parent/fork 标记）做全量验证与残差证伪，而不是枚举全部写入方。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9ceab5d6-9c2f-4cf4-a73d-9ed7ecee9969:3032:422ec3f8d6a9aea1852f
evidence_refs: learning:learn:e62cb53263f3
created_at: 2026-10-02T10:55:32.190504+08:00
updated_at: 2026-10-02T10:55:32.190504+08:00
---
## Trigger
需要为某数据层的跨 session/实体重复记录定案根因与归属规则，候选机制空间大（复制、迁移、重放、竞态、损坏），且已有权威文档登记过重复规模

## Discriminator
当时已可观察的事实：重复 attempt_id 连同微秒级 ts、call_id、payload 逐字段一致（设计文档§7/搜索回执已给出）。任何再生成类机制（重放、重试、并发写）必然产生新的时间戳与运行时 id；只有字节级物理复制能保留全部易变字段。系统内被文档化的物理复制机制是 session-fork。

## Short path
- 从重复记录本身提取字段一致性指纹：比较易变字段（ts、运行时 id）与业务字段（payload）；未知量：复制 vs 再生成
- 只读系统内文档化的字节级复制机制代码（fork/migrate/backup），确认其保留哪些字段、重分配哪些字段；未知量：该机制能否解释逐字一致
- 推导次级预测并与观测对账（大历史复制超 10MB 滚动阈值 ⇒ 双方成多段目录，解释重复集中在多段层）；未知量：层分布成因
- 写只读验证脚本：为每个重复 id 建 parent/fork 谱系边，预测 100% 可链接；未知量：是否存在无解释重复
- 对复制解释不了的残差单独证伪（如 settled 在所有会话均不存在），按失败模式重新定性；未知量：残差归属
- 冻结归属规则成 mini-design，实现+幂等复跑+回归门，与既有文档数字精确对账后停止

## Stop conditions
- 重复集合 100% 被谱系链接解释（UNLINKED=0），且最大簇数字与权威文档既有记录精确对账
- 残差已被证伪性证据重新定性并落档
- 谱系链接率显著低于 100%，或重复对易变字段存在差异 ⇒ 放弃复制假设，转向重发/竞态路径

## Verification
- 抽样重复对做字段指纹检查：确认易变字段逐字一致，而非仅业务字段一致
- 读复制路径源码确认：ts/payload 原样保留、仅重分配 id 类字段
- 全量谱系链接：每个重复 id 均有 parent/fork 边，输出 UNLINKED 计数
- 数字对账：簇统计与决策文档既有登记一致；修复后幂等复跑 0 新增；回归门全绿

## Counterexamples
- 重复记录业务字段一致但时间戳/id 不同 ⇒ 属重发/重放/至少一次投递，应查写入点幂等与去重，本方法的复制谱系路径会误导
- 单文件内部的重复（截断/追加损坏、同文件重复追加）无跨实体谱系边，不适用
- 复制路径合法重写了部分字段（如本集 session_id/seq/event_id 设计性重分配）且覆盖了易变字段时，指纹需按'该复制路径保留哪些字段'重新定义，不能照搬 ts 一致性
