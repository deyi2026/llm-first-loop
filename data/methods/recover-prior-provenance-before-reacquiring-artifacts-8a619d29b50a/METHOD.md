---
method_id: recover-prior-provenance-before-reacquiring-artifacts-8a619d29b50a
name: recover-prior-provenance-before-reacquiring-artifacts
description: 在补完或核验上一轮结论时，先用会话事件流/证据恢复这些结论的精确来源（仓库、包名、版本、路径），再按该来源定向取回材料；不要先按猜测的本地路径、缓存目录或同名包/文件做宽搜索。只有事件流没有来源线索时，才扩大发现范围。
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:6aec21cb-8703-4ef8-9229-f57e73cdb86e:61:a5784c615f832f3d8bac
evidence_refs: learning:learn:225b29941b53
created_at: 2026-09-24T00:19:03.447050+00:00
updated_at: 2026-09-24T00:19:03.447050+00:00
---
## Trigger
用户要求继续、补完或核验此前结论，且需要重新获取文档、代码或包材料；本地缓存路径、版本或包名可能已变化。

## Discriminator
存在可审计的会话事件流/证据，能记录上一轮动作使用的精确 source/provenance；任务本身是延续而非全新发现。

## Short path
- 列出需要补完的未核验结论，不立即搜索文件。
- 查询会话事件流/证据，定位这些结论来自哪个精确来源和路径。
- 用事件流给出的仓库/包/路径做最小定向获取；本地路径先确认存在再 grep。
- 若事件流无来源线索，才按名称/内容做有限发现，并记录新 provenance。

## Stop conditions
- 每个未核验结论都有与事件流来源一致的权威材料支撑。
- 发现需要纠正旧结论时，已有事件流或权威来源回执证明纠正依据。
- 事件流无 provenance 且已完成一次有限发现，转入正常核验。

## Verification
- 最终引用的仓库、包名、版本、路径与事件流/证据中的来源一致。
- 没有仅凭名称相似就判定来源错误或材料无效。
- 本地路径操作前已有 pwd/ls 或等价存在性回执。

## Counterexamples
- 用户本轮已给出精确 URL、路径或包版本，可直接定向获取。
- 全新任务没有上一轮事件流/证据，需要正常发现来源。
- 材料是临时产物且 provenance 不重要，只需当前内容即可回答。
