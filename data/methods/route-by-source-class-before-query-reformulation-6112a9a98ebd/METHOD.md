---
method_id: route-by-source-class-before-query-reformulation-6112a9a98ebd
name: route-by-source-class-before-query-reformulation
description: 当目标事实具有明确来源类别（带时间戳的先前会话决定→持久 records/memory 库；规范/设计文档→docs；运行时工件→evidence/文件）时，先按来源类别选库、用贴近原文的词汇一次查询；该库未命中且回执明确（非超时）且查询词贴合记录原词汇时，把未命中当作库排除证据切换库类别，而不是在同一库内反复改写关键词、也不是转成全目录文件枚举。本集若首查 records(kind=memory)，1 次调用即命中 10:02 决定原文，可省去此前 8 次扩散检索。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:31:48a12ca6739e6a5e28b8
evidence_refs: learning:learn:56219d291238
created_at: 2026-09-23T10:38:41.082758+00:00
updated_at: 2026-09-23T10:38:41.082758+00:00
---
## Trigger
需要找回一条早先产生、尚未落档的事实（如'今天 10:02 讨论定的设计方向'），且已知其大致产生时间/场景；或某检索库已用贴题关键词查询返回明确未命中回执。

## Discriminator
目标事实带精确时间戳且产生于先前会话讨论——其权威存储是持久 records/memory 库，而非 docs（该决定尚未写入 docs，写入正是本任务）也非当前会话 evidence（早于本会话）；docs 与 evidence 两次明确'未命中/未找到'回执构成库排除证据，剩余权威库只剩 records。此判断仅依赖当时已知的时间戳属性与未命中回执，不依赖后来命中的结果。

## Short path
- 按来源类别路由：时间戳会话决定 ⇒ 直接 search_records(kind=memory)，用决定核心短语（选择权/分档/裁剪/越权）一次查询，命中即取得原文与 provenance（2026-09-23T10:02:45Z）
- 每库一次贴题查询确认配套文档是否存在（Almeida 草案是否已落 docs）；未命中即认定只存于 memory，不再全目录枚举
- 读取同命名惯例现有文档（DECISION-*.md）作为格式模板
- 对新文档将引用的每条外部条目（守则 Q5 原文、SPEC R3）做定向核实后再引用
- 写入 → 回读核对 → 声明交付物，停止

## Stop conditions
- 已从权威库取得目标事实原文及其 provenance（时间戳与库别吻合），不再对其余库做'再确认'检索
- 配套文档存在性已用每库一次贴题查询判定完毕
- 文档写入后回读一致、全部引用已逐字核实

## Verification
- 命中记录的时间戳与已知事实时间吻合（10:02:45Z ↔ '10:02 决定'）
- 引用的守则/SPEC 条款与源文件原文逐字核对（Q5、R3），未沿用记忆转述
- 写入后 read_file 回读，行数与结构和声明一致

## Counterexamples
- 目标决定已落成 DECISION-*.md 文档：docs 才是首查库，records 仅作补充 provenance
- 目标是运行时工件（截图/网络响应/进程态）：应查 evidence/文件/进程层，records 与 docs 均不对口
- 查询词是自己的转述而非记录原词汇：库内未命中可能是词汇失配，此时在同类库内改写关键词是正确动作，不应立即换库
- 已知 memory 库存在打标错误或进程回滚覆盖（本工作区有先例）：records 未命中不能证明不存在，扩大检索正当
