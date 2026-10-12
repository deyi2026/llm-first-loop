---
method_id: resolve-anaphoric-file-refs-via-session-delivery-records-first-7c2e41a9b-43ebef1c58d2
name: resolve-anaphoric-file-refs-via-session-delivery-records-first-7c2e41a9b3d0
description: 当用户以回指方式引用本会话刚交付的具体文件（如「这两个文件」）并要求对其操作时，「是哪些文件」的候选集已被会话上下文限定为个位数交付物。应优先查询会话权威交付记录/Evidence（present_files 声明）取得精确绝对路径，而不是对仓库做文件名枚举。本集第一次 search_files 命中 20 条截断结果且可见列表不含目标，紧接的一次定向证据查询即给出两个交付物的精确路径、大小与角色描述。拿到路径后立即转入实际任务（转换/修改/再交付），发现阶段即停止。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6f6aaff7-affa-4ddd-ba99-dd5932331bbc:126:61d637ba14161ed2e1e5
evidence_refs: learning:learn:5a6e377ae5ab
created_at: 2026-09-29T14:32:40.913078+08:00
updated_at: 2026-09-29T14:32:40.913078+08:00
---
## Trigger
用户消息用指示性/回指表述（「这两个文件」「刚才那份」）指称本会话刚产出或刚交付的少量具体文件，并要求对其执行转换、修改或再交付等操作。

## Discriminator
回指本身把候选集从「仓库任意文件」限定为「本会话刚交付的 N 个产物」（N 由上下文给出，本集为 2），且会话存在结构化交付记录（present_files Evidence：精确绝对路径、大小、角色描述）可作权威索引。当时可见的反证：仓库级文件名搜索命中 20 条截断、可见结果不含目标文件。

## Short path
- 解析用户回指：「这两个文件」=本会话刚交付的产物；未知量=精确路径
- 一次定向查询会话交付/Evidence 记录（present_files/deliverables），取回精确绝对路径并核对数量与回指一致（2/2）
- 一条命令确认转换工具可用（which pandoc + 版本，可与 ls 交付目录合并）
- 对两个 .md 执行 pandoc MD→DOCX 转换
- 机械验证输出：OOXML/zip 结构可解析 + 正文关键词与字符数抽查
- 以正确 schema present_files 声明交付并停止

## Stop conditions
- 从会话权威记录取得全部被引用产物的精确路径（数量与回指隐含数量一致）后，停止发现，转入实际任务
- 定向证据查询无命中且即时上下文也无路径时，才降级为目录级定向搜索或询问用户

## Verification
- 解析出的文件数量与用户回指隐含数量一致（「两个」→2）
- 路径来自会话交付记录，且角色描述与用户所指内容相符
- 转换后输出通过结构验证（OOXML/zip 可解析）与内容抽查（关键词命中、字符数）

## Counterexamples
- 请求本身是开放式发现（「找出仓库里所有含 X 的文件」）：仓库级枚举正是正确动作，不套用
- 用户引用的文件非本会话产出/交付（历史会话或外部来源），交付记录无命中：需文件系统搜索或直接询问用户
- 被引用文件的精确路径已逐字出现在紧邻上文消息中：直接使用，无需任何搜索
- 会话存在多批交付、回指语义不唯一：先按交付时间/角色消歧，仍不唯一则询问用户，而不是扩大为全库枚举
