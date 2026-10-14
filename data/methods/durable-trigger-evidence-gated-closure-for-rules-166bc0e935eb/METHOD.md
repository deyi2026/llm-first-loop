---
method_id: durable-trigger-evidence-gated-closure-for-rules-166bc0e935eb
name: durable-trigger-evidence-gated-closure-for-rules
description: 规则/流程文档落盘≠会被使用。用户质疑'会被使用吧'或新设规则时，先对实际触发面（活动goal、任务图pending、records/docs索引）做单次廉价探测：全空则规则只是死文件。补救不是口头保证，而是补建durable载体：goal+pending task（验收标准取自规则原文、关闭强制evidence）+可检索experience。写入任何记录前重读原文取精确参数。汇报时区分'闭环就绪'与'已走完'并列出未覆盖通道。下次新设规则时同会话直接建全闭环，免去用户质疑后的返工。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:2d3fd645-2639-44ec-9f14-2a96c1c807fe:78:73cb0e0615198f0407e8
evidence_refs: learning:learn:50f256437167
created_at: 2026-10-14T12:35:17.427455+08:00
updated_at: 2026-10-14T12:35:17.427455+08:00
---
## Trigger
用户质疑某规则/流程/约定在未来特定时点是否真的会被执行（'会被使用吧''怎么保证不漏'），或刚完成一条新规则的设立与落库

## Discriminator
触发面探测回执：无活动goal、records/docs检索均未命中、任务图无pending项，而文件确实存在——该事实把'如何保证被使用'从无数种口头/记忆承诺缩为'补建缺失的durable载体'。第二个判别事实：规则原文可读且含精确入口/参数/边界，任何记录内容应从原文拷贝而非凭印象。

## Short path
- 逐通道单次探测触发面：goal状态、records检索、docs索引、文件存在性，标出空缺通道（每次调用回答一个明确未知量，不做全量枚举）
- 读规则原文，提取精确入口脚本、参数、保护边界与验收步骤——禁止把凭印象的路径写进任何durable记录
- 创建durable goal + pending task：acceptance逐条取自规则原文，开启evidence_required使关闭必须附执行回执，形成不依赖会话记忆的触发层
- 沉淀可检索experience记录（如实标注验证状态）承担检索层，弥补docs索引未覆盖时的可发现性缺口
- 汇报时区分'闭环就绪'与'闭环已走完'，明确列出未覆盖通道；首次真实执行后回写规则文档记录表，验证状态才升级

## Stop conditions
- 规则已由机械强制层（CI、git hook、cron等）在实际触发点执行，durable task属重复载体
- 规则是单会话一次性指令，不存在未来触发时点
- 用户仅询问规则内容而非执行保证——直接读原文回答即可

## Verification
- 新建task的acceptance每条都能从规则原文推导，不含凭记忆引入的参数
- task关闭时evidence_refs齐备（如预览→执行→复验的回执链），否则闭环未真正走完
- 首次真实执行后规则文档的记录表被回写，规则状态从'已建立'升级为'已验证'

## Counterexamples
- 触发已被CI/hook机械覆盖时再建goal/task，徒增任务图噪音与过期待办
- 高频变动的草案规则过早挂durable task，会积累垃圾pending项
- 对无未来触发时点的一次性约定套用此流程，是把一次性成本误判为制度成本
