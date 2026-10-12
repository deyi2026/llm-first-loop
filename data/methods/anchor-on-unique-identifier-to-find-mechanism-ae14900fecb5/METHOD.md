---
method_id: anchor-on-unique-identifier-to-find-mechanism-ae14900fecb5
name: anchor-on-unique-identifier-to-find-mechanism
description: 当状态/工具回执返回含唯一字面标识（schema 名、专有字段名、全局部署 ID）的结构化数据，而下一个未知量是『谁生产/消费它、对应操作流程是什么』时，先用这些精确字符串做定点定位：浅层 find 找数据/manifest 文件，grep 标识（scope 到已知的 code_root 的 src/docs/tests）找实现与操作文档；不要先做模糊关键词的 evidence/docs/files 宽搜，也不要全库无界 grep。唯一标识近乎零误报，能把搜索空间从『全仓库』缩成两三个可读文件。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:928:3bc785b9e37301b8acf5
evidence_refs: learning:learn:892d71c631e5
created_at: 2026-09-18T04:20:28.596498+00:00
updated_at: 2026-09-18T04:20:28.596498+00:00
---
## Trigger
结构化回执已给出全局唯一、可直接 grep 的字面标识（schema 字符串、专有字段名、ID），且回执同时给出了可作 grep scope 的路径（如 code_root），而任务需要弄清该数据的读写机制或操作步骤

## Discriminator
回执中是否存在非通用的唯一字面量（schema 版本串、复合专有字段名、全局 ID）——存在即意味着任何包含该字符串的文件定义性地属于机制本身（实现/文档/测试），模糊关键词搜索在此时是低信息动作

## Short path
- 读状态回执，提取唯一标识（schema 串、专有字段名、ID）与 scope 路径（code_root/runtime_root）
- 用标识定点定位：runtime_root 浅层 find 找 manifest 数据文件；grep 标识但 scope 到 code_root 的 src/、docs/、tests/，命中实现、操作指南、测试三类文件
- 读实现确认操作语义（操作是专用命令还是手改数据；派生字段如哈希如何计算），读指南确认人机分工与步骤
- 按指南核对前提（目标 HEAD、产物在位、新旧提交是否触及产物目录），全部通过才生成命令
- 命令中所有 expected/CAS 值来自刚读到的回执，禁止凭记忆或旧会话填入

## Stop conditions
- 实现代码与操作文档双重确认了操作方式，前提检查（HEAD、产物、diff）全部有直接证据，命令已生成并含读回校验
- 唯一标识 grep 无任何命中（机制不在本仓库）→ 此条因果边断裂，才扩大到模糊 docs/files 搜索或外部询问

## Verification
- grep 命中应同时覆盖实现、文档、测试三类文件并互相印证；只有一类命中时先补另一类再下结论
- 生成命令前用只读子命令（show/status）读回当前代次/版本作为 expected 值，不硬编码
- 对『无需重建/可直接发布』类结论必须持有直接 diff 证据（如新旧提交对产物目录零改动）而非推断

## Counterexamples
- 标识是通用词（id、version、name）→ grep 泛滥误报，应改用路径 scope 或组合键，本方法不适用
- 回执内容已完整回答用户问题 → 直接停止分析，不追生产者代码
- 标识只出现在运行时数据文件、由外部系统生成（仓库内无实现）→ 边断裂，需宽发现或问人
- 仓库巨大且无 scope 路径可用 → 无界 grep 会超时，应先从回执或目录结构推出 scope 再执行
