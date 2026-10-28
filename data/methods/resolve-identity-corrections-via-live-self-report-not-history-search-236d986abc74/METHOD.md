---
method_id: resolve-identity-corrections-via-live-self-report-not-history-search-236d986abc74
name: resolve-identity-corrections-via-live-self-report-not-history-search
description: 用户用模糊标识（近似代号、相对时间如'昨天部署的'、按角色指代）纠正或询问多个相似运行实体（服务/模型/工件）中'哪个是哪个'时，先用运行实体的自述事实一步定位：进程完整命令行、endpoint 自报元数据（如 /models 的 name+description）、ps lstart 启动时间。这三类机器事实通常同时解决'是哪个'与'何时部署'两个未知量；仅当自述缺失、多候选并列命中、或用户质疑自述本身时，才扩大到事件流/归档/历史日志搜索；两个相似实体的同源性用 config/README 的 base_model 等身份字段或权重指纹裁决。本集首轮命令已拿到两个候选的命令行与自述模型名，却先翻了旧事件流与归档（miss），ps lstart 才一步给出'昨天部署'的时间线。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72b1f325-1293-4022-9fb8-46f58685873e:55:a876dc20a8224f99836b
evidence_refs: learning:learn:2b2eb2eb101a
created_at: 2026-10-17T10:32:08.858200+08:00
updated_at: 2026-10-17T10:32:08.858200+08:00
---
## Trigger
用户纠正或询问若干相似本地服务/模型/工件的身份归属，且使用模糊标识（近似名字、相对部署时间、按角色指代），同时候选进程或 endpoint 处于可查询的运行状态

## Discriminator
候选进程的完整命令行 + endpoint 自报元数据，已能按用户描述中的可区分维度（规模/角色/名称片段）唯一命中目标（如全场唯一带目标规模标识的服务）；而时间性描述（'昨天部署'）由 ps lstart 一步可验，无需检索历史事件流

## Short path
- 取每个候选的完整命令行 + 自述元数据 endpoint（模型名/描述），锚定各候选的自报身份
- 用用户描述里的可区分维度（规模/角色/名称片段）对自报身份做唯一匹配，锁定目标候选
- 对候选 pid 取 ps lstart，验证相对时间描述并同时排除长期运行的旧进程
- 若需证明与另一相似实体不同源：读其 config/README 身份字段（base_model/架构规格），必要时再做权重指纹比对，'同规格不同源'的表述要留证据
- 模糊代号无命中时直接向用户要全名；仅当自述缺失或并列命中才检索事件流/归档

## Stop conditions
- 身份（命令行模型路径=endpoint 自报名=README/config 身份字段三方一致）与时间线（进程启动时间）均已锚定且与用户纠正一致，输出修正映射并停止
- 自述元数据缺失、多个候选并列命中或用户质疑自述本身失真时，才转入历史记录搜索或向用户澄清

## Verification
- 最终身份三方一致：进程命令行中的模型路径 = endpoint 自报模型名 = README/config 身份字段
- 时间断言与 ps lstart 一致；'同架构不同模型'类结论须引用 base_model 或权重指纹，不得仅凭名字相近推断

## Counterexamples
- 模糊描述同时命中多个自述候选（如两个同规模服务并行）：自述不足以消歧，应先向用户要全名或查部署记录，而不是硬选一个
- 目标服务已停止、无活进程可查：部署时间线只能靠历史/归档还原，历史搜索是正路而非绕路
- 用户怀疑自述本身失真（加载器指错权重、endpoint 返回缓存元数据）：须直接做权重级校验，命令行与自报名不能作为终局证据
