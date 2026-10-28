---
method_id: adjudicate-artifact-behavior-at-definition-not-generative-oracle-96f39a8947d7
name: adjudicate-artifact-behavior-at-definition-not-generative-oracle
description: 对生成式工件的行为/机制问题（是否滚动、为何变化），当 provenance 已点名定义源（SVG 动画元素、生成脚本、schema）时，先解析定义回答，再用受控重渲染确认实际生效；派生静态快照只能证明'有差异'，不能裁决'为什么'。已有机械量化测量时，不把同一性/运动裁决交给生成式 VLM：首读与硬数字矛盾或幻觉实体即停，升级到定义层而非换输入重问。本集：两次 VLM 裁决互相矛盾且在 pelican 场景幻觉出'dog'，最终靠解析 SVG 分层 translate 动画+冻结重渲染（dx=-130、SAD 6×降）定案。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:a893a41e-be0e-416f-8859-a47020156e3e:156:eb5ad60a8e45944af521
evidence_refs: learning:learn:e14779622a34
created_at: 2026-10-17T15:27:09.213218+08:00
updated_at: 2026-10-17T15:27:09.213218+08:00
---
## Trigger
需要回答生成式工件的『行为/机制』问题（是否滚动、是否运动、为何变化），且 provenance/目录同时列出定义源（SVG 动画元素、生成脚本、schema）与派生静态快照（preview 拼图/截图）；或已持有对派生快照的机械量化测量，正考虑让生成式 VLM/LLM 裁决同一性或运动。

## Discriminator
当时已知：同一目录里定义源与派生快照并存（gen.py + pelican-bike.svg + preview_sheet.png），快照是被生成的副产品，行为由定义文件因果决定；且机械测量已给出硬数字（树线带 51.6%/66.7% 像素变化 @mx>8），而首次 VLM 读数与之矛盾并幻觉出场景中不存在的实体（pelican 场景里的 'dog'、'red bike'）——矛盾在第一次读数后即已可见，足以判定该 oracle 对此问题不可信。

## Short path
- 状态恢复时先给 provenance 中文件分类：哪份是行为定义源（SVG/生成脚本/schema），哪份是派生快照（preview/screenshot）；未知量：权威工件是谁。
- 直接解析定义源的行为声明（枚举动画元素+祖先链、常量断言如 SCROLL_NEAR 与轮周长的绑定）；未知量：该行为是否被定义、是否生成器意图。
- 受控重渲染确认定义生效：冻结 t=0/t=Δ 各渲一帧，对关键带做平移交叉相关（best dx、SAD 降幅）；未知量：实际渲染是否实现定义的行为。
- 派生快照仅用于修正既有报告数字（57%→51.6%），不作为'为什么'的裁决材料；未知量：需要更正的对外数字。
- 若已误问生成式 oracle 且首读与硬数字矛盾/幻觉实体：不再换输入重问，立即回到第 2 步。

## Stop conditions
- 行为问题已由定义源+受控重渲染双重证实，且与既有机械测量互不矛盾
- 快照层仅剩的数字修正已完成
- 首次生成式读数即与机械测量矛盾或幻觉实体 → 终止同源 oracle 询问

## Verification
- 最终结论同时引用定义证据（动画元素/常量）与受控渲染证据（best dx 且 SAD 显著下降），二者互相印证
- 报告中百分比来自对实际被分析文件的当场重测，而非上一轮记忆数字
- 确认所读定义文件与被分析产物出自同一生成过程（时间戳/生成链一致）

## Counterexamples
- 工件没有定义源（外部交付的 PNG/视频）：只能做工件层定量测量，VLM 可当假设生成器而非裁决者
- 问题本身是感知/美学判断（风格是否协调）：生成式读数就是正确工具，数字回答不了
- 定义可能与实际产物脱节（产物被手工改过、runtime 与源码版本不一致）：单读定义会答成'意图'而非'实际'，必须配受控重渲染实测
