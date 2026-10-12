---
method_id: search-miss-is-tool-domain-question-read-store-then-matcher-493354d9df7a
name: search-miss-is-tool-domain-question-read-store-then-matcher
description: 当检索工具对精确 id 返回"未找到"、而用户或先前证据表明记录应存在时，不要把 miss 当成存在性结论，也不要向其他子系统（UI 文案、无关源码）扩散。先一跳直读权威存储文件取得 ground truth（存在/status/时间戳），再复现 miss，然后读检索实现的匹配域（call-site 的 summary_keys 与 matcher 的 hay 构造），对比查询 token 是否落在可检索字段集合内，最后用正/负对照查询证实。"未找到"否定的只是工具的检索域，不是存储本身。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:51:715d6908485926da855b
evidence_refs: learning:learn:9c1f2fab9c42
created_at: 2026-09-18T13:34:19.076286+00:00
updated_at: 2026-09-18T13:34:19.076286+00:00
---
## Trigger
检索/查询工具对精确 id 或已知存在的关键词返回未找到，且该工具是已知路径存储文件的可读封装；或自己上一轮基于 miss 得出"不存在/未批准"类结论后被用户质疑

## Discriminator
权威存储路径已知且直接可读（如上一轮已直读确认过的 jsonl 文件），且用户断言操作确已发生——工具 miss 与可直接验证的存储真值之间的分歧，把假设空间从"不存在/未写入/时序/权限/工具bug"缩到"检索域是否包含查询字段"这一个读一次实现即可验证的未知量

## Short path
- 直读权威存储文件，按精确 id 定位记录：存在性/status/时间戳即 ground truth
- 用同一 id 调一次检索工具，确认 miss 可复现（分歧成立）
- 读检索实现的对应 kind 分支与匹配函数定义，提取可检索字段集合（summary_keys + content_key 构成的 hay）
- 对比查询 token 与可检索字段集合：id 不在域内 → 形成根因假设
- 正/负对照证实：用已知在域内的值（内容词、status 词）查询命中，同 id 仍 miss
- 根因证实即停，输出原因与修复建议；不再枚举与用户问题无关的子系统文案

## Stop conditions
- ground truth（直读）+ miss 复现 + 匹配域差异 + 正负对照四者齐备
- 直读发现记录确实不存在 → 转向存在性/写入侧排查
- 域内值的对照查询也 miss → 转向索引过期/分词/编码类假设，不再读字段表

## Verification
- 正对照：用记录中确定存在于可检索字段的词查询 → 应命中
- 负对照：同 id 查询 → 应 miss；正负对照同时成立才接受根因
- 最终结论引用具体实现位置（call-site 字段表 + matcher hay 构造）作为 provenance

## Counterexamples
- 记录确实不存在（用户记错或环境不同）：第 1 步直读即终止，读检索实现是浪费
- 检索是外部黑盒 API、无源码可读：应改为黑盒正/负对照探测而非读实现
- miss 由索引延迟/最终一致性造成：先重试或核对时间线，读 matcher 无意义
- 用户抱怨的是 UI 显示本身而非 AI 侧判断：渲染层排查才是正路，存储优先序不适用
