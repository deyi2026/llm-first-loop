---
name: method-self-distill
description: 在一个 Agent/工具任务已经完成或明确失败后，如果出现长路径、反复试错、多个失败工具、明显绕路、用户纠正后才成功或希望把本次教训转成下次更短行动路径时使用。基于可观察的任务、工具动作、Evidence/结果和用户反馈进行独立 Method 蒸馏；重点学习“如何从轨迹抽出判别方法”，不保存或复述原始思维链，不把候选自动升级成规则或强制工作流。
---
# Method Self-Distillation

目标：把一次真实任务中的“绕远以后才做对”压缩成下次可复用的判断与行动方法。

不要恢复或复述隐藏 reasoning。只使用可审计事实：用户目标、action/tool trace、工具结果、Evidence/provenance、最终结果、用户纠正。

## 核心算法：Friction -> Discriminator -> Counterfactual -> Generalize -> Falsify -> Compress

不要自由散漫地“反思”。严格按下面六步走。

### 1. Friction：找第一处搜索空间开始扩散的位置

不是找“最后哪个动作错了”，而是找：

> 从哪一个动作开始，后续动作开始枚举更多可能性，却没有针对一个明确未知量逐步缩小范围？

只指出一个**最早的**位置。

典型信号：

- 从读取一个明确线索跳成全目录/全工具/全站枚举；
- 同一 source class 反复换参数；
- 已有直接 provenance/引用边，却改成宽搜索；
- 已拿到足够结果，却继续“再确认几个”。

### 2. Discriminator：找当时已经存在、却没有充分利用的判别事实

这是整个方法最关键的一步。

问：

> 在进入 Friction 之前，模型**当时已经看见的什么事实**，本可以把候选空间从很多个缩到一两个？

必须满足 **knowledge-at-time**：只能使用当时已经出现的事实，不能拿后面才读到的答案倒推。

好的 discriminator 是具体可观察事实，例如：

- HTML 正文为空，但明确引用一个 hydration script；
- traceback 明确给出失败函数和参数类型；
- 当前源码定义已经展示准确函数签名；
- 工具回执明确是 404，而不是 transient timeout。

坏的 discriminator：

- “应该更聪明一点”；
- “应该先分析”；
- “后来发现正确答案在 X”。

### 3. Counterfactual：重建“不作弊”的最短可信路径

从任务起点重新走一次，但每一步只能使用**前一步已经暴露的信息**。

要求：

- 每一步都说明它要解决哪个未知量；
- 新动作必须由上一步的 discriminator/provenance 导出；
- 不使用未来答案、隐藏 ID、事后才知道的路径；
- 一旦用户所需事实已被权威来源验证，停止。

目标不是绝对最少工具数，而是**最短可信路径**。

### 4. Generalize：只抽象一层

把具体文件名/网站/API 名换成“关系”，不要一下抽成空泛哲学。

坏抽象：

- “网页任务要认真分析。”
- “永远先读 JS。”
- “不要用 search_files。”

好抽象：

> 当当前 artifact 明确指向“缺失内容的生产者/加载器/来源”时，优先沿这条 causal/provenance edge 继续，而不是先做宽枚举。

这条方法保留了判断空间，但明显缩小搜索空间。

### 5. Falsify：主动构造反例

至少给一个“这条方法不应该套用”的情况。

如果找不到反例，通常说明抽象太空泛或太绝对。

反例必须改变关键 discriminator，例如：

- HTML 已直接包含完整目标正文；
- 页面引用的 JS 只是 analytics，不生产目标内容；
- 源码定义与当前 runtime 版本不一致，必须查真实运行 schema。

### 6. Compress：压成 Method Card

只保留能改变下次行动的内容。不要复述 episode。

推荐长度：约 300~700 中文字；复杂方法可稍长，但必须远短于原始轨迹。

```yaml
name: <short-name>
status: candidate
trigger:
  - <observable situation>
discriminator:
  - <fact that narrows search early>
short_path:
  - <step driven by currently known fact>
branch_on_evidence:
  - observation: <fact>
    next: <changed hypothesis/action>
stop_conditions:
  - <condition>
verification:
  - <check>
anti_patterns:
  - <pattern>
counterexamples:
  - <when not to apply>
programizable:
  - <deterministic part, if any>
model_owned:
  - <semantic judgment that must remain model-owned>
why_shorter: <one sentence explaining search-space reduction>
```

# Teacher exemplar：离线网页抓取包

下面是一个完整样板。学习的是“怎样提炼”，不是记住这些文件名。

## Episode facts

用户目标：从离线网页抓取包重建最终文章标题和 token。

真实动作：

1. `read_file(page.html)` -> 页面主体只有 `Loading article...`，同时明确出现 `<script src="assets/app.js">`。
2. `search_files(*)` -> 枚举整个抓取包。
3. `read_file(network_manifest.json)`。
4. `read_file(stale_search_snippet.txt)` -> 旧摘要，不是当前页面真值。
5. `read_file(responses/navigation.json)` -> 导航数据，与任务无关。
6. `read_file(responses/api_v2_article_7842.json)` -> 得到正确标题/token。
7. `read_file(assets/app.js)` -> 看到页面实际通过 `/api/v2/article/7842` hydrate。

最终答案正确，但读了几乎整个包。

## Teacher distillation

### Friction

第一处搜索空间扩散是第 2 步 `search_files(*)`。

原因不是“search_files 工具不好”，而是第 1 步已经给了一个更窄、更因果的下一跳，却没有先沿它走。

### Discriminator

第 1 步已经存在的关键事实：

> HTML 本身是 loading shell，并明确引用 `assets/app.js` 作为页面运行脚本。

这个事实当时就足以把“所有文件都可能有答案”缩成“先确认这个脚本是否负责加载目标内容”。

注意：这里**没有使用后来第 7 步才读到的 API endpoint** 来作弊。

### Counterfactual shortest credible path

1. 读起始 HTML；未知量：目标正文是否已在 HTML 中？
2. 发现正文是 shell，且有明确 hydration script -> 读该 script；未知量：目标内容从哪里加载？
3. script 若给出具体 API/source endpoint -> 在离线 capture metadata 中只解析这个 endpoint 对应的 response；未知量：哪个 captured response 是目标来源？
4. 读准确 response，取得标题/token。
5. 验证 response 与 script 指向的 endpoint 一致，停止。

这条路径不需要先读 stale snippet 或 navigation，也不需要先把整个目录扫完。

### Generalize one level

候选方法不是“网页先读 JS”，而是：

> **Follow explicit provenance before broad discovery**：当当前 artifact 已明确指向“缺失内容的生产者/加载器/来源”时，优先沿该 causal/provenance edge 获取下一事实；只有这条边断掉或无法解释目标内容时，才扩大搜索范围。

### Falsify

不要套用的反例：

- HTML 已经含完整目标正文 -> 直接分析并停止，不追 JS；
- script 只是 analytics/广告，与目标内容无关 -> 不沿它继续；
- 页面没有任何 producer/source 线索 -> 此时才需要目录/网络/搜索层面的 broad discovery。

## Final Method Card example

```yaml
name: follow-explicit-provenance-before-broad-discovery
status: candidate
trigger:
  - 当前 artifact 未包含目标内容，但明确指向可能生产/加载该内容的另一个 artifact/source
discriminator:
  - 是否存在与目标内容因果相关的显式 script/import/endpoint/ref/provenance edge
short_path:
  - 先判断当前 artifact 是否已经足够
  - 若不足且存在显式 producer/source edge，沿该 edge 验证下一来源
  - 只有该 edge 断裂、无关或不足时才扩大搜索范围
branch_on_evidence:
  - observation: 当前内容已足够
    next: 停止发现，进入分析
  - observation: 显式 edge 指向具体 producer/source
    next: 沿 edge 读取并验证
  - observation: 无显式 edge 或 edge 被证伪
    next: 扩大到目录/网络/搜索发现
stop_conditions:
  - 已从与 provenance 一致的来源取得用户所需事实
verification:
  - 确认最终来源与上游 artifact 的引用/endpoint/provenance 一致
anti_patterns:
  - 在已有窄 provenance edge 时先全量枚举候选
  - 读到任务无关结果后仍继续沿同一宽搜索分支
counterexamples:
  - 静态 artifact 已直接包含完整目标内容
  - 显式引用只是 analytics 等与目标内容无关资源
programizable:
  - 提取 script/import/ref/endpoint 等机械引用关系
model_owned:
  - 判断哪个引用与用户目标语义相关、何时证据已足够
why_shorter: 用已存在的因果关系把“所有候选”先缩成一个可验证下一跳。
```

# 小模型执行要求

如果你是能力较小的模型，不要再做长篇自由反思。按下面顺序输出中间草稿即可：

1. `FRICTION=<一个最早动作>`
2. `DISCRIMINATOR=<当时已知的一条事实>`
3. `SHORTEST_PATH=<3~6 步>`
4. `GENERAL_RULE=<只抽象一层>`
5. `COUNTEREXAMPLE=<至少1个>`
6. 最后输出一个 Method Card。

如果在第 2 步找不到满足 knowledge-at-time 的 discriminator，就停止并输出 `INSUFFICIENT_EVIDENCE`，不要靠延长思维补答案。

# Promotion 边界

本 episode 只能生成 `candidate`，不能自己验证自己。

后续在不同任务中使用时：

- `task_applicability=not_evaluated`；
- 比较正确率、工具调用数、无信息重复、失败数、post-sufficiency actions；
- 必须包含反例任务；
- 无收益或出现固定偏差 -> refine / supersede / invalidate；
- 有独立任务行为证据后才考虑升级为稳定 Method/Skill。

# 职责边界

程序可以：记录 action/event/evidence/provenance、识别“值得复盘”的机械摩擦事实、限制 reflection 的资源预算。

程序不能：决定哪条语义方法是正确答案、自动判定 task applicability、把 candidate 强制注入所有未来任务。

模型负责：从事实中找 discriminator、重建可信短路径、抽象方法、构造反例与判断迁移性。
