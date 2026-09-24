---
method_id: known-issue-citation-resolve-originating-record-first-23882c95be22
name: known-issue-citation-resolve-originating-record-first
description: 用户把某缺陷当作既定事实引用（如'遗留悬空 runtime'）并征求处置建议时，该命名通常源自项目内某次审计/报告。应先用命名中的独特字面 token 直查 record/episode 存档（grep data/episodes 等），取回原始审计拿到精确实体名、数量与定性；再以这些精确标识符做一次定向源库 grep 复核承载文件。只有记录缺失、过期或复核不一致时才退回源码宽枚举。当前态前提（服务代次、树态）另走 live 状态查询。本集先按短语直译关键词多轮 miss、再全库 grep+超时，最后才由精确标签 rg 意外命中当日 08:13 审计存档，多花约 6 次调用。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:318:2a5fbe56e390bdfccd85
evidence_refs: learning:learn:685759b3c59c
created_at: 2026-09-24T09:02:12.865096+00:00
updated_at: 2026-09-24T09:02:12.865096+00:00
---
## Trigger
用户消息以'遗留/已知/此前发现'等口径把一个缺陷或发现当作既定上下文引用（而非提问是否存在），请求修复或处置建议；且项目存在 records/episodes 审计存档通道。

## Discriminator
用户断言口径本身即 provenance 边：'悬空 runtime' 这类非通用命名必有起源记录；且早期 search_records 命中已显示记录库存有完整审计/经验正文。该事实把'全库哪里有悬空指针'缩成'先取回定性的那条审计记录'，而不是把短语直译成双语关键词反复检索或转向源码宽枚举。

## Short path
- 识别用户口径为'既定事实引用'→ 未知量收敛为：该定性的原始审计记录在哪，而非'源库里哪里有悬空指针'
- 用命名中的独特字面 token（如 'runtime:'、'悬空'）直接 grep record/episode 存档（含 data/episodes/*.jsonl），可一次同时命中起源审计与承载文件线索
- 由审计记录取得精确实体名/计数/定性（如 2 个目标值、kind 枚举无 runtime、不可水合），再以精确标识符做一次定向 rg 复核源库承载文件与语义去向（docs 基础名/阶段映射）
- 记录与源库复核一致 → 停止发现，进入处置建议；不一致或无记录 → 才扩大为源码级枚举推导
- 处置依赖的当前态（服务代次/树态/重启契约）并行走一次 live 状态查询，与考古分离，不互相混入

## Stop conditions
- 起源记录已给出实体清单/计数，且一次精确标识符 grep 与当前源库结果互相印证
- 确认记录通道查无该 token 任何存档，此时才转源码/运行时宽枚举
- 记录结论与源库复核冲突 → 以源库现值推翻记录，停止沿记录分支继续

## Verification
- 审计记录中的计数/实体与源库 rg 结果互相印证（本集：2 目标值 × 3 文件，kind 枚举确无 runtime）
- 最终建议同时可区分地引用起源记录结论与当前 live 状态（服务 stable 代次、git 树态），两类证据来源明确

## Counterexamples
- 用户是在问'是否存在此问题'而非引用已知事实 → 无 provenance 边可沿，须一手取证，不能只信记录
- 命名是通用词（如'性能问题''一些报错'）无独特 token → 无法定位起源记录，直接走源码或运行时取证
- 起源记录之后源库已被修改（承载文件增删改）→ 命中记录后仍须一次精确 grep 复核，不一致时以现值为准
- 记录早于日志/审计通道上线，或引用的是外部跨项目审计 → 存档查不到，宽枚举是必经路径而非绕路
