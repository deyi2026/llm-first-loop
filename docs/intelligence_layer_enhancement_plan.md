# 智能化增强层可执行方案（记忆 / 语义检索 / 演进）

> 状态: v1.0 | 生成: 2026-08-20 | 依据: GitHub 深度调研（ECC / deer-flow / uteke / Prime Agent / Mem0 / Zep / LangMem / TiMem）
> 核心结论：**底座已就绪（Embedder 协议 none/hash/api + SemanticRetriever 已存在），缺激活、非重写**。

## 1. 背景与目标

用户要求：在智能化增强层（记忆 / 语义检索 / 演进）方向，先从 GitHub 找最新最热门的项目深度调研，再借鉴总结出更适合本 AI 的方案。

现状：系统已有记忆机制（extract_enabled / memory_top_k / memory 类型 fact|decision|convention / [[memory]] 记忆块），但语义检索未激活（embedding_provider=none），记忆检索以关键词为主，演进闭环靠人工审阅。

## 2. GitHub 调研综述（2026-08 最新热门）

| 项目 | 定位 | 关键设计 | 对本系统借鉴点 |
|:---|:---|:---|:---|
| **Mem0**（mem0ai/mem0） | 通用记忆层（Universal memory layer） | 多级记忆（User/Session/Agent）、single-pass ADD-only 提取（单次 LLM 调用、只增不覆盖）、agent 事实一等公民、**实体链接（entity linking）**、**多信号检索（语义+BM25+实体并行融合）**、时序推理；LoCoMo 92.5 / LongMemEval 94.4 / BEAM(1M) 64.1 | ① 多信号检索→RRF 融合；② ADD-only 防覆盖；③ 实体链接增强召回 |
| **TiMem** | 五层时序记忆树（TMT） | CLS 互补学习系统理论：原始对话 L1→会话摘要 L2→每日总结 L3→每周 L4→人物画像 L5；查询按复杂度自适应选层；token 省 52% | 分层记忆 + 自适应检索深度（简单查低层/复杂查高层） |
| **Zep** | 情节记忆图谱 | 事件时序感知（Graphiti 时序知识图谱）、跨会话记忆 | 时序感知：记忆带时间维度，回答"最近/上月"类问题 |
| **LangMem** | 工作记忆 + 长期存储 | LangChain 生态原生，create_memory_manager | 工作记忆/长期存储分层理念（对应本系统当前上下文 + 压缩档案） |
| **Prime Agent**（★14.6k） | 递归 LLM agent 框架 | RLM prompt-as-a-variable；Continual Harness：4 类条目（prompt/memory/skill/subagent）×3 操作（create/update/delete）×2 作用域（global/local）；/refine 用 4096 token AUTO_REFINE_REVIEW 审查门过滤噪音 | ① 记忆条目类型化 × 操作 × 作用域矩阵；② 审查门过滤噪音（已有 self_inspection 类似） |
| **ECC / deer-flow / uteke** | agent harness 操作系统 / 工作流 / 本地记忆层 | 记忆已成 agent 基础设施标配；uteke 本地优先、零云端 | 印证方向：记忆/语义检索是必备组件，非可选增强 |

## 3. 关键借鉴提炼

1. **记忆是基础设施，不是功能**：所有热门 agent 框架均内置记忆组件，本系统已有雏形，方向正确。
2. **多信号融合检索**（Mem0）：语义 + BM25 关键词 + 实体匹配并行打分融合——本系统 RRF 多信号融合方向与此一致，属已验证路径。
3. **ADD-only 写入**（Mem0 最新）：单次 LLM 调用提取、只增不覆盖，避免 UPDATE/DELETE 的复杂性与一致性风险——本系统记忆累积 + 压缩档案另存天然符合。
4. **分层记忆 + 自适应深度**（TiMem）：原始细节→会话级→日级→周级→画像，按查询复杂度选层——对应本系统"当前上下文 + 压缩档案 + 记忆库"分层，可显式化。
5. **审查门过滤噪音**（Prime Agent）：写入前用独立审查过滤低质记忆——本系统 self_inspection_enabled 已有同类机制。
6. **本地优先**（uteke）：零云端依赖，隐私与可用性兼得——本系统 Embedder 协议支持 none/hash 本地档，不强制外部 API。

## 4. 本系统现状盘点

| 能力 | 现状 | 差距 |
|:---|:---|:---|
| Embedder 协议 | 支持 none/hash/api，embedding_provider=none | 未激活（hash 档可零依赖启用） |
| SemanticRetriever | 已存在 | 未接入记忆检索主链路 |
| 记忆类型化 | fact/decision/convention | 无衰减、无时间维度 |
| 记忆溯源 | [[memory]] 块 + search_records 可溯 | 无显式衰减策略 |
| 多信号融合 | RRF 概念已有（EVO 演进） | 未落地语义+关键词融合 |
| 演进闭环 | submit_evolution + 人工审阅 | 常规化程度不足 |

## 5. 四阶段方案（缺激活、非重写）

**阶段一：激活语义检索（hash 档，零依赖）**
- embedding_provider 切 hash，SemanticRetriever 接入记忆检索主链路；
- 记忆检索 = 关键词（现有）+ 语义（hash 相似度）双路并集，top_k 融合；
- 验收：search_records(kind=memory) 对同义表述命中率提升。

**阶段二：记忆类型化 + 衰减 + 溯源**
- 记忆条目显式带 created_at / 类型 / 来源（会话/工具/评估）；
- 时间衰减：旧条目降权（借鉴 Zep 时序 + Mem0 temporal reasoning）；
- 溯源增强：每条记忆可回溯到来源会话/事件（search_records 已有基础）。

**阶段三：RRF 多信号融合**
- 检索 = 语义（hash/api）+ 关键词（BM25 类）+ 实体（可选）并行打分，RRF 融合；
- 对齐 Mem0 已验证的 multi-signal retrieval 路径。

**阶段四：演进闭环常规化**
- 自我评估（self_evaluate）触发 → 沉淀经验（save_experience）→ 演进建议（submit_evolution）→ 执行登记（evolution_complete）常态化；
- 记忆/检索指标纳入周期自检（如缓存命中率、记忆命中率）。

## 6. 风险与取舍

- **hash 语义 vs API 语义**：hash 档零依赖但语义能力弱（字面相似），API 档（如 embedding API）语义强但引入外部依赖；分阶段：先 hash 激活链路，再按需升级 api 档。
- **记忆膨胀**：ADD-only + 衰减 + 审查门三管齐下控制。
- **性能**：语义检索 + RRF 增加检索延迟，需控制 top_k 与缓存。

## 7. 关联演进建议

- EVO-20260810（智能化增强层相关演进）待核对状态；
- 阶段一（激活 hash 语义检索）建议作为首个可执行演进提交。

---
*文档依据：2026-08-10~12 两次 GitHub 调研（raw 直链规避 API rate limit）+ 2026-08-20 Mem0 仓库抓取 + 2026 四大记忆框架横评（掘金）。*
