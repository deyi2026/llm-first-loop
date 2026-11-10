---
method_id: gate-receipt-field-absence-disclose-not-backfill-22c7d682945d
name: gate-receipt-field-absence-disclose-not-backfill
description: 用户把放行结论定义为合取式门槛（如 真实PASS 且 P0=0 且 P1=0）并指定必报字段，而准入/审查闸的唯一正式终态回执 qualification=PASS 却未回显部分必报字段（显式计数、实跑模型）时，报告分三层：①原样报告回执可证实的正式事实（qualification、child_id、SHA、覆盖数、artifact_reviewed）；②逐字段披露回执未回显项——缺失≠0≠失败，预算候选模型列表≠实跑模型；③可引用工具契约对签发语义的内嵌校验说明作证据，但数字条件是否视同满足由闸主裁定。防止两类错：把字段缺失冒充为 0，或因回执不全而无视已真实签发的 PASS。
aliases: PASS了但回执没有P0P1计数怎么报, 放行条件差数字证据, 缺计数不能当零报, 审查通过但必报字段没回显, 终态回执字段不全如实披露
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:971e3282-cf26-4c73-bd5c-bac1223e4a7a:0:7c78960facd2f957a47f
evidence_refs: learning:learn:b281fd8499f4
created_at: 2026-11-10T07:42:16.037153+08:00
updated_at: 2026-11-10T07:42:16.037153+08:00
---
## Trigger
用户要求按合取式条件（正式终态 PASS ∧ 显式计数门槛等）报告放行，并点名必报字段；工具的真实终态回执已返回 qualification=PASS，但回执键集中缺少部分必报字段（如 P0/P1/P2 计数、实跑模型）。

## Discriminator
报告时刻逐字段比对：终态回执实际返回的键集 vs 用户必报清单。任一字段缺失是可观察事实——缺失既不是 0，也不是审查失败；预算块里的候选模型数组也不能确证实跑对象。这个差集决定报告形态，而不推翻已签发的正式结论。

## Short path
- 先原样报告回执可证实的正式事实：qualification、child_id、材料 SHA256、paths 覆盖数、artifact_reviewed——这是 Host 唯一签发语义，如实陈述。
- 对每个必报而回执未含的字段逐条写明『回执未回显』：计数缺失就写缺失，模型缺失就说明仅有候选模型列表、不能确证派发对象。
- 若工具契约文本对签发语义有说明（如 PASS 签发前内嵌 SHA 与计数校验），作为『缺失字段是否被上游校验覆盖』的证据披露，但注明这是契约推论，不冒充为回执中的数字。
- 合取门槛中回执不可证的那一肢交回闸主裁定：报告『PASS 已真实签发＋数字条件回执不可证』，不单方面宣告放行，也不宣告失败或触发额外动作。

## Stop conditions
- 必报字段全部在终态回执中显式回显 → 直接逐字报告并按合取条件给出结论，无需裁决层；
- qualification=pending → 属运行中回执，字段缺失是预期，继续按配速轮询而非报告缺失；
- qualification=REVISE 或失败 → 按任务书 STOP，不进入任何下游动作。

## Verification
- start 与 status 终态回执的绑定字段（child_id、candidate_sha256、paths 清单）逐项一致；
- 报告中每个数字、模型名、覆盖数都能指回某条真实回执字段，无任何值来自推断补齐；
- 缺失披露与契约引文分开呈现，读者能区分『回执说的』与『我推的』。

## Counterexamples
- 回执本就显式给出 P0/P1/P2 计数 → 无字段缺口，直接核对数字出结论，不做语义裁决；
- 用户门槛是单目条件（只要真实 PASS 即可）→ 无合取缺口，PASS 即可报放行；
- 回执仍是 pending/中间态 → 缺字段不代表终态信息缺失，应继续轮询而非披露缺失。
