---
method_id: close-full-defect-list-before-recheck-b05eaa027921
name: close-full-defect-list-before-recheck
description: 当验证/审查步骤返回可枚举的缺陷清单（多条、带位置或严重度）时，把清单当作闭包集：下一次补丁必须对每一项给出处置（修复 / 证伪为误报 / 显式延期并附理由），随后的单次重跑要对照整张清单逐项复核，而不是只看刚修的项。本集看图审查一次列出4项（含「100%压柱顶·中等」与「小标题重叠·严重」），补丁只按最严重项的像素几何改了小标题，「数字贴柱顶」在下一轮审查原样复现，白费一轮完整重渲染+视觉审查。按整清单一次闭包，省掉每漏一项就多付一轮 render+review 的循环。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:9f3f9ab8-30d9-4a2d-9f58-148054503778:453:342772e0de9faadbe889
evidence_refs: learning:learn:9ad752fc8645
created_at: 2026-10-10T19:30:18.960324+08:00
updated_at: 2026-10-10T19:30:18.960324+08:00
---
## Trigger
一个验证/审查/看图检查步骤刚返回枚举式缺陷报告（≥2 条具体条目，带位置或严重度），下一步动作是打修复补丁并重跑/重渲染同一产物。

## Discriminator
报告本身已是逐条闭包清单。knowledge-at-time：修复前的回执里已同时列出「100% 压柱顶（中等）」「小标题重叠（严重）」「标签行距（中等）」「繁简混用（轻微）」；补丁说明只覆盖小标题几何（「柱高240顶到y=190，小标题写在196」），证明清单中其余已定位、可同批修的条目未被处置。

## Short path
- 机械解析审查回执为编号清单：条目、位置/几何、严重度。
- 对每条在源码/几何中定位：能修的随同一补丁修掉；不能立即修的显式标记 deferred 或 suspected-false-positive 并附一句理由。
- 单次重跑/重渲染，不做逐条增量重跑。
- 复核时对照原清单逐项判定 closed / deferred / false-positive，检查面覆盖全部条目而非仅刚改的区域。
- 全部条目有处置且 closed → 进入下一步；仍有 reopened → 只对剩余子集循环。

## Stop conditions
- 原清单每一条都已映射到 closed / deferred(带理由) / false-positive(已核实) 之一。
- 继续重跑只会重复检查已回答过的条目，没有新的未知量。

## Verification
- 把新一轮审查结果与原清单逐项 diff：任何「上一轮已列出、本轮原样复现」的条目即为补丁未闭包的直接证据。
- 每条 deferred / false-positive 处置都附一句可核查的理由，不允许静默跳过。

## Counterexamples
- 条目间互相冲突（如给数字留白会挤压小标题）：按相容批次分组修复，可多于一轮，但每轮仍须闭包整批，不逐条挤牙膏。
- 清单含疑似误报（审查者读错图）：先核实该条再修或证伪，不盲改。
- 反馈是开放式 prose、无可枚举条目（「排版感觉不对」）：先转成显式清单，本方法不适用。
- 某条需要设计层改动而非参数调整：单轮闭包不可行，应显式拆批并说明，而不是硬塞进一个补丁。
