---
method_id: anchor-content-search-on-observed-literal-tokens-8d7925c691d2
name: anchor-content-search-on-observed-literal-tokens
description: content 类搜索是字面子串匹配，不是语义检索。每次构造查询词必须逐字取自已观察材料：此前命中行的原文短语、用户原话中的标识符、import/docstring 中的符号名、回执中的精确路径。概念级检索要锚定『必然与目标同现的 token』（规则 ID、函数核心名、路由路径），而非把概念翻译成自拟自然语短语或猜测完整函数签名。一次无匹配后，先从已有回执提取更准 token，再发下一次查询。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f1523846-ee16-4c78-9f53-7abf782eac2b:589:d60d7379cd8aa524950b
evidence_refs: learning:learn:b32d45a1d715
created_at: 2026-09-30T00:24:26.467097+08:00
updated_at: 2026-09-30T00:24:26.467097+08:00
---
## Trigger
在代码/证据库用 content 搜索定位规则、实现或入口；且此前回执或用户原话已展示可逐字复用的 token（标识符、原文短语、路径）

## Discriminator
回执本身证明 content 为字面匹配（无匹配回执显示 content=...）；且已观察命中行中存在与目标同现的逐字 token——本集第 1 次命中行已逐字给出权威短语『不因 accepted 放宽』与精确路径 src/llm_loop/...，随后仍用释义词『审批不放宽』、猜测名『def _evolve_review』、探索性 ls llm_loop/ 各浪费一次调用

## Short path
- 用用户原话中的精确标识符（requires_human）做首次定位（未知量：规则实现在哪）
- 直接复用命中行中逐字出现的短语/ID（『不因 accepted 放宽』）二次定位铁律落点（未知量：判定顺序在哪定义）
- 读定义文件，从 docstring/import 提取符号名与命令名（未知量：入口在哪）
- 入口定位用稳定核心 token 做多选一 grep（evolve_review|evolve-review|evolution/review），不猜完整签名
- 取证覆盖定义+入口+文档三层后停止搜索，进入修改

## Stop conditions
- 精确 token 检索已命中定义处并读取到判定代码
- 连续 2 次未锚定查询无命中时，禁止第三次猜测，强制改从回执提取 token 或直接读已见路径

## Verification
- 回查每次查询词能否在此前回执/用户原话中逐字找到；找不到即为违规查询
- 无匹配次数应为零或仅首探性一次；按本集最短路径可省 ≥3 次失败调用

## Counterexamples
- 全新主题、已观察材料中目标概念零字面出现：只能先做宽概念词枚举，锚定规则无从谈起
- 工具本身是语义/向量检索：逐字短语锚定反而收窄召回，应按语义表述查询
- 已有直接 provenance（import 边、路由表、回执中完整路径）：直接读文件比再发一次搜索更短
