---
method_id: verify-inline-insert-position-via-rendered-geometry-1c1dfae6aa19
name: verify-inline-insert-position-via-rendered-geometry
description: 向已渲染的富文本编辑器（Draft.js 类）分步插入有序内联媒体（图片须落在指定小节位置）时，计数/唯一性/行缺失类校验无法发现错位：失败占位图可冒充唯一 src，全部追加文末也仍是 6/6 PASS。判别点：插入回执若显示定位未生效（marker 未被替换、caret 由 Range/Selection 合成），位置即未验证；编辑器把所有块包进单一容器时 DOM 树遍历会重复计数/误报前置标题，渲染几何（bounding-rect y 值）才是权威顺序证据。行动：回执异常即冻结清理类后续动作，用单次几何探针比对锚点与插入项 y 交错；顺序错则改走真实输入事件（真实点击定 caret→回车腾空块→粘贴 File）重建，再以同一探针复验。可省去多轮树遍历试错与事后删标记引发的块合并吞段。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:8432bab4-9ec8-4407-a69c-0cd2c90dce64:1679:15af2c0f40125efc4d7c
evidence_refs: learning:learn:65d6ada24356
created_at: 2026-10-15T17:12:08.263535+08:00
updated_at: 2026-10-15T17:12:08.263535+08:00
---
## Trigger
向所见即所得/富文本编辑器（或任何『内容顺序即正确性』的目标文档）分步插入有序内联内容（如图须落在指定小节后），且现有验收校验只覆盖计数/唯一性/行级缺失，不含位置信息

## Discriminator
插入动作自身回执已显示定位失败：marker_gone:false（图插在标记旁而非替换它）、或 caret 由 Range/Selection 合成——框架编辑器不认合成光标，内容会默认落到当前光标/文末；此时任何『数量 PASS』都不构成位置证据。次级判别：树遍历探针输出异常一致（所有图的前置标题相同）或重复计数，说明探针本身不可信，应改用 bounding-rect y 坐标

## Short path
- 插入正文+定位标记，确认标记在位
- 逐项插入媒体后先读回执：marker 未被替换或 caret 为合成 → 位置未验证，冻结清理/发布类后续动作
- 单次几何探针：取各锚点（标题）与各插入项的 bounding-rect y 值，断言 y_前锚 < y_项 < y_后锚，且无重复计数
- 若错位（如全部堆在最后锚点之后）：放弃 DOM Range 定位，改真实输入事件原语——点击目标块行首→回车腾出空块→点击空块→派发携带 File 的 paste，落位天然正确、全程无删除动作
- 同一几何探针 + 计数/唯一性/残留标记复验，全过即停

## Stop conditions
- 每个插入项的 y 值严格落在其目标锚点与下一锚点之间，探针自检无重复元素，计数/唯一性/残留标记同时通过
- 位置不影响正确性的任务（内容本就应统一附在文末）在计数/唯一性通过后即停，不强制几何验证

## Verification
- 对每项断言 y_前锚 < y_项 < y_后锚；探针输出含重复元素时先修探针再下结论
- 已发布场景补公网回读：h1/h2 层级、图片域名、关键串缺失，确认渲染态与编辑器态一致
- 区分占位图与真图：核对 src 域名与实际尺寸（失败占位常为统一小尺寸+同一 src）

## Counterexamples
- 静态页面、每块为独立顶层 DOM 子节点且无懒加载：DOM 顺序即视觉顺序，树遍历可靠，几何探针是多余开销
- 内容位置无关（如附件固定列表在文末）：计数+唯一性校验已足够
- 图片懒加载未渲染时 y 坐标为 0 或不可用：需先触发渲染或改用服务端文档序作为顺序源
