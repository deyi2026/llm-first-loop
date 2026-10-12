# openJiuwen vs Dify / Coze / BiSheng：底座层真差异与生态锁定风险

> 证据基准：GitHub API 实时查询（2026-10-10 14:xx CST）。
> 标注约定：**[已核]** = 本轮工具直接取到的事实；**[厂商自报]** = 来自华为/官方页面，无第三方审计；**[推断]** = 我的分析，非事实。

---

## 0. 先更正两处前提

1. **HiAgent 属于字节跳动火山引擎，不是第四范式。** [已核] 火山引擎官网 `volcengine.com/product/hiagent`，百度百科载运营主体为北京字跳网络技术有限公司。我上一条消息把它与第四范式并列是错的。
2. **"编排层 vs OS 层"这个二分法本身是可滑动的**，不能直接当分析框架用。见第 2 节，给出一个可验证的替代边界。

---

## 1. 生态位硬数据对照 [已核]

| 项目 | 归属 | Stars | Forks | License | 最近 push |
|---|---|---:|---:|---|---|
| **Dify** | langgenius | **158,046** | 24,951 | 改 Apache（非 OSI） | 2026-10-10 |
| MaxKB | 1Panel | 22,933 | 3,172 | GPL-3.0 | 2026-10-10 |
| Coze Studio | coze-dev | 21,696 | 3,128 | **Apache-2.0（真开源）** | **2026-07-29** ⚠️ |
| BiSheng | dataelement | 12,031 | 1,977 | Apache-2.0 | 2026-10-10 |
| **openJiuwen** | openJiuwen-ai（24 仓） | **7,791 合计** | — | Apache-2.0 ×20 | 2026-10-10 |
| └ 其中平台内核 | agent-core 等 | **1,117** | — | Apache-2.0 | — |
| └ 其中应用/示例 | jiuwenswarm 等 | 6,674 | — | Apache-2.0 | — |

**关键读数：**
- openJiuwen 内核 star **1,117**，Dify **158,046** → **约 141 倍差距**。
- openJiuwen 6,674 star（85%）集中在 `jiuwenswarm`（5,984）这个**消费级聊天应用**上，不是平台内核。这说明它当前的社区势能是 C 端应用带起来的，不是底座被采用。
- Coze Studio 自 2026-07-29 起 **73 天无 push**，而同期 openJiuwen 每日提交。这是一条被文章忽略的重要信号。

### 许可证的真实分层（文章完全没讲，但对企业采购最关键）[已核]

我直接拉取了 `langgenius/dify` 的 LICENSE 原文，其在 Apache 2.0 之外附加：
- **a. 多租户禁止**：未经书面授权，不得用 Dify 源码运营多租户环境（"租户 = 一个 workspace"）。
- **b. 品牌锁定**：不得移除/修改前端 LOGO 与版权信息。
- **c. 单方改约**：贡献者同意 Dify 可随时"放宽或收紧"协议，且贡献代码可用于其云业务商业化。

→ **Dify 不是 OSI 开源，是 source-available。** openJiuwen 纯 Apache-2.0 在许可证自由度上**优于** Dify 和 GPL-3.0 的 MaxKB。这是本次开源在企业侧最实质、最少被讨论的收益。

---

## 2. "底座层 vs 编排层"的真实边界：有没有 inference data plane

文章/Dify 叙事把差异归为"编排 vs OS"，这个划分不可证伪。真正可验证的硬边界是 **[推断，基于仓库构成]**：

> **是否自带推理执行平面（inference data plane），即能否在不依赖外部 vLLM/SGLang/云 API 的前提下承接请求。**

按这个边界重新归类：

| | 自带推理平面 | 性质 |
|---|---|---|
| **openJiuwen** | ✅ `agent-infer` + `agent-runtime` + `model-router` | 全栈 |
| Dify | ❌ 必须外接模型服务；沙箱（dify-sandbox）是代码隔离不是推理 | 编排 + 应用运行时 |
| Coze Studio | ❌ 同上 | 编排 |
| BiSheng / MaxKB | ❌ 同上（BiSheng 强在 RAG/文档管线，MaxKB 强在知识库 UX） | 编排 |

**openJiuwen 的分层确实是唯一的真分层** [已核，仓库构成]：

```
agent-protocol (C++, MCP+A2A SDK)   ← 协议层
agent-infer / agent-runtime          ← 执行平面 ★ 关键差异
agent-core (Python, 446★) / agent-core-java (42★) / agent-runtime-java (32★)
agent-studio (184★, TS) / agent-dx / skillhub
agent-memory / agent-tools / agent-plugin / relay
agentos-enterprise (8★, 仅 8 star —— 商业版差异的所在)   ← [推断] 商业能力未开源
jiuwenswarm / jiuwensymbiosis / deepsearch / sciencediscovery / iCode  ← 应用层
```

`agentos-enterprise` 仅 8 star 且未公开实现 → **"共享 90%+ 内核"的说法在代码层是可信的**（商业版只是薄薄一层企业管控），因为可核的仓库清单里企业版就是单薄一层。但**"90%" 是厂商自报**，无法从代码精确验证。

---

## 3. 生态锁定的四个真实机制

### 机制一：芯片层锁定 —— 最强，且不可通过开源规避 ★核心

这是 openJiuwen 最需要被讲清楚、也最容易被一笔带过的一点 [推断]：

**它的核心卖点「算力亲和」（Agent Hint 接口 + 会话感知调度）只在昇腾/CANN 栈上成立。**
官方自报 TTFT −57.46%、E2E −27.61%、前缀缓存 +33%、池化缓存峰值 −25.24% [厂商自报] —— 这四项本质是**调度器针对特定硬件的 KV cache 与批处理策略优化**。同样的代码跑在 NVIDIA + vLLM 上，收益大概率趋近于零。

所以准确的表述不是"华为开源了一个免费的 AgentOS"，而是：

> **华为开源了一层"昇腾 Agent 编程接口"，用 Apache-2.0 许可证降低采用门槛，最终变现路径回到昇腾一体机与伙伴方案。** [推断]

参照系非常清楚：CUDA 生态的开放程度远低于 Apache-2.0 的名义承诺。openJiuwen 在**许可证**上比 CUDA 开放，在**能力边界**上比 CUDA 窄。

### 机制二：协议层锁定 —— 弱，且方向相反

`agent-protocol` 提供 MCP / A2A 的 **C++ SDK** [已核]。这是**降低**锁定而非制造锁定：走开放协议的应用，理论上可换运行时。唯一残留绑定是 C++ 扩展与 CANN runtime 的耦合。

**结论：openJiuwen 不构成"平台锁定"，它构成"硬件绑定"。** 二者性质完全不同——前者你付钱能解，后者你付钱也解不了，只能换供应商。

### 机制三：许可证锁定 —— openJiuwen 最松，方向对它有利

见第 1 节。要注意的**反向风险** [推断]：正因为纯 Apache-2.0，一体机厂商、ISV、以及昇腾的竞争芯片厂商（如寒武纪、以及未来 NVIDIA 在中国的合规方案）都可以自由 fork 并替换底层绑定。所谓"生态锁定"在这个许可证下是**结构上不成立的**。华为的护栏不在法律层，而在**昇腾硬件本身 + CANN 工具链成熟度 + 伙伴认证体系**这三件钱买不到也不开放的东西上。

### 机制四：组织与文档密度 —— openJiuwen 明显劣势

- 24 个仓库碎片化，单个内核仓 `agent-core` 446 star，issue/PR 承载能力与 Dify（158k star、1,121 open issues）差数量级。
- 双语言实现（Python + Java 各一套 core/runtime）**平摊了社区密度**——两套都达不到 Dify 单实现的生态门槛。
- 优势项：提交极其活跃（多个仓 2026-10-10 当日推送），比停更 73 天的 coze-studio 更值得押注。

---

## 4. Manus 不在同一层，文章并列是叙事需要

Manus 系（蝴蝶效应，5 亿美元融资）是**单任务执行型 general agent**：交付一个"能干活的任务结果"，不做平台、不做多租户、不承诺开发者生态。
Dify/Coze/openJiuwen 是**平台**：交付"让别人造 agent 的能力"。

两者唯一的交叉点是" Manus 可以被接进平台作为执行后端"。**不在同一层竞争**，强行并列是文章为了"双层结构"叙事服务，不是分析。

同理，企业级正式战场 openJiuwen 的真实对手不是 Dify，是**华为云 AgentArts 自己**——即开源版 vs 商业版的关系；Dify/Coze 只是昇腾一体机买家备选清单上的第二、第三项。

---

## 5. 结论

1. **生态位：赢不了，也不会去赢。** 开源项目生态位是路径依赖的——Dify 从 2023-04 累积至今，158k star 与 24.9k fork 的迁移成本不会因为 2026 年大厂入场而重置。openJiuwen 内核 1.1k star 且 85% 势能在 C 端应用，短期内不构成 Dify 的替代项。
2. **真正的差异化只有一条：它是目前唯一把国产芯片推理栈暴露成可编程接口的开源 Agent 平台。** 对昇腾客户这是真痛点；对 NVIDIA / 其他国产芯片客户，价值接近零。
3. **许可证自由度上它确实赢了 Dify**（Apache-2.0 vs 多租户禁用的改 Apache）——这是文章没提、但对要自建平台的企业最有实操价值的一点。
4. **必须打折的部分**：四项性能数字、90% 内核、GAIA/BrowseComp-Plus 榜首、邮储银行落地，全部是自报，无第三方复现。本文所有标注 [厂商自报] 处均如此。

### 什么会证伪我第 3 节的核心判断

**如果 agent-infer 在 CUDA + vLLM 上被第三方复现出接近量级的 TTFT/E2E 收益**，则"算力亲和 = CANN 绑定"的判断错误，openJiuwen 的价值半径会大幅扩大。应持续盯这个复现结果——这是整个判断的唯一支点，目前无任何外部证据。

---

### 一句话

> openJiuwen 不是"免费的 Dify 中国版"，它是**用 Apache-2.0 卖昇腾**——许可证最自由，能力半径最窄，最强绑定在代码之外。
