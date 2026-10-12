---
method_id: shared-derivation-failure-propagate-fix-to-batch-0876646f429f
name: shared-derivation-failure-propagate-fix-to-batch
description: 当一批待执行调用共享同一条参数推导规则（如 绝对路径 = 假设根 + 搜索返回的相对命中路径），且首个调用以与来源证据矛盾的方式失败（搜索刚命中该路径并给出符号级上下文，read 却报文件不存在）时，该失败证伪的是推导规则（根前缀/换算），而非单个实例。应立即停止对同批兄弟调用复用同一推导：先一次性诊断真实根（依据失败回执提示、已知仓库布局或一次廉价根目录确认），再用修正后的推导把整批挂起调用在同一轮内一并重发，而不是让同一错误在兄弟调用上重放第二次。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:504:8d79c79ce557c374595f
evidence_refs: learning:learn:afbbee95314b
created_at: 2026-09-23T23:51:02.490541+00:00
updated_at: 2026-09-23T23:51:02.490541+00:00
---
## Trigger
多个待执行 read/调用的路径或参数由同一条规则从上一步成功的 search/list 结果推导而来，且其中第一个以 not-exists 等与来源证据直接矛盾的回执失败

## Discriminator
失败回执与来源事实的矛盾：search 刚返回该相对路径且含符号/行上下文，read 却报'文件不存在'并提示该路径已登记无效——搜索根≠假设的工作区根，错在路径换算，不在目标是否存在

## Short path
- 对每个目标对象做针对性内容搜索定位（逐对象窄搜索，不做全库枚举）
- 首个命中路径 read 报 not-exists 时，立即判定错误变量是推导根前缀：依据回执提示、已知 src-layout 布局或一次廉价根目录列取确认真实根
- 用修正后的前缀把同批全部挂起 read 在同一轮一并重发
- 校验每个 read 内容包含搜索命中引用的符号/行上下文，随后继续实现细节阅读，无需重新搜索

## Stop conditions
- 修正推导后整批兄弟调用全部成功，且内容与搜索命中的符号/行上下文吻合
- 修正后仍失败 ⇒ '换算错误'假设被证伪，退回对单个文件重新 search/list 定位

## Verification
- 每个重发 read 成功且文件内容与 search 命中给出的符号、行号上下文一致
- 同一构造不再产生第二个 not-exists 失败

## Counterexamples
- 只有一个挂起调用、无兄弟批次：无批可传播，直接修正该条路径即可
- 失败是瞬时性（超时/权限）而非存在性：不存在'来源命中 vs 不存在'的矛盾，应原样重试而非改路径
- 搜索索引过期、文件确已移动或删除：修正前缀后仍会失败，正确动作是重新搜索定位，而非继续做前缀手术
