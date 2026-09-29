---
method_id: search-contested-term-before-its-topic-entities-ee94824b383d
name: search-contested-term-before-its-topic-entities
description: 当用户质疑的真正未知量是一个术语的含义/所指（某流程、机制或角色的名字），该术语字符串本身就是最高价值的检索键：先对术语本身做文件名/内容搜索，1-2 跳即可落在其定义点（目录、治理/协议文档），再据此回答适用性。不要先去枚举术语所修饰的主题实体。若术语也 0 命中，说明它是外部概念：应向用户索要原文或声明基于转述，而不是对主题实体做同义词扫荡。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc07ea9d-6ab9-44b7-b385-65eea54960b6:521:22a54aff8a4ef73d79ae
evidence_refs: learning:learn:dc9bc9ab6d6d
created_at: 2026-09-28T19:37:35.341491+08:00
updated_at: 2026-09-28T19:37:35.341491+08:00
---
## Trigger
用户消息中含一个含义未知的、疑似本仓原生术语的词，且『该词在此语境指什么/适不适用』是待答问题的核心；工作区可被 search_files 检索。

## Discriminator
未知量是『词义』而非『实体事实』：争议词以可检索字符串原样出现在用户消息里（本集为 'pilot'）；项目原生术语几乎必然物化为目录名/脚本名/文档标题，因此对术语的定向检索是对其定义点的直连 provenance edge。辅助判据（当时已见）：前几次对主题实体词（cbm/codebase-memory 系）的搜索已全部 0 命中，说明答案不键在那条线上。

## Short path
- 从用户消息提取争议术语原文（'pilot'）作为第一检索键；未知量：该词在本仓指什么。
- search_files 对 'pilot' 做文件名+内容搜索 → 命中定义点（本集实际存在：evals/pilot/、run_pilot.py、GOVERNANCE.v1.md）；未知量：定义点在哪。
- 读 GOVERNANCE.v1.md → 词义落定：AgentPilot = 冻结 runner 的三臂 harness A/B，lfl 是其一条臂；未知量：该词义是否否定『给 CBM 做 pilot』。
- 结合已观察的 CBM 系 0 命中回执作答：范畴错误 + 采信门槛成本论，给出两个 read-only 不确定量与澄清问题；停止。

## Stop conditions
- 定义点文本已给出足以回答用户问题的词义与判据（本集：CBM 非三臂之一 + gate 成本）。
- 术语检索也 0 命中 → 词是外部概念：向用户索原文，或显式声明『基于转述作答』，不再扫主题实体。

## Verification
- 答案中的词义断言能在定义点文本中找到原句支撑（如 'lfl 是一条臂' 须在 GOVERNANCE/REPORT 中有对应表述）。
- 任何『工作区不存在 X』的断言须引用具体 0 命中回执或 stat 失败回执，而非凭印象。

## Counterexamples
- 术语是泛用词（test/run/report，甚至 'pilot' 在通用仓库会大量命中）：裸词搜索被噪音淹没 → 先加目录/扩展名/上下文限定，或词义本已共识时直接跳过搜词。
- 用户并未质疑词义：双方对术语含义已共识，争议在事实层 → 直接查事实，定向搜词是浪费动作。
- 术语明确来自用户可提供的外部文档（本集 minimax 转述的 CBM 文档）：正解是请求原文，而非在一个必然不含该文档的仓库里对其实体做同义词连发。
