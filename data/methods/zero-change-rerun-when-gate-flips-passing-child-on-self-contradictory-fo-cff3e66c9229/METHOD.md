---
method_id: zero-change-rerun-when-gate-flips-passing-child-on-self-contradictory-fo-cff3e66c9229
name: zero-change-rerun-when-gate-flips-passing-child-on-self-contradictory-format-contract
description: 异步准入闸（如 review_admission 的 article_publish/git_push）把内容结论 PASS/P0=0 的独立 Reviewer 审查判成 REVISE、且理由只涉及结论块输出格式契约自相矛盾（判据要求 FINGERPRINT/SHA256 二选一，提示词正文又要求 SHA256 行）时，缺陷在闸的合同而非工件：先用同一回执内『child 内容结论 vs Host 终判理由』字段对照当场定侧，再定点读一次闸的判定源确认矛盾，然后保持 candidate SHA 零改动原样重跑（上限2次）；过闸后才发布，并把闸侧缺陷如实写进回执。若理由落在工件侧、child 内容本身未过、或矛盾确定性复现，则停止重跑，走最小修正或保持 BLOCKED。防止两条歧路：为矛盾格式去改已 PASS 的稿件；把闸缺陷误当工件缺陷反复修。
aliases: 审查内容过了却被格式打回, Reviewer过了Host不给过, 再交一次审不改内容, 闸的规则自己打架, 发布审查卡格式要不要动稿子
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1a2df79-d6bc-44db-9e7e-31fd295724f4:0:c5870b9c26b3e12294bd
evidence_refs: learning:learn:a2eaf33579cd
created_at: 2026-11-11T16:34:59.956568+08:00
updated_at: 2026-11-11T16:34:59.956568+08:00
---
## Trigger
异步准入/审查闸回执为 REVISE 或拒绝，但同一回执内独立 Reviewer 的内容结论是 PASS、P0=0、指纹一致，且 Host 拒绝理由只指向 reviewer 结论块的输出格式契约本身互相矛盾，完全不涉及稿件、页面或工件内容缺陷。

## Discriminator
第一次 REVISE 回执里并排可见两个字段：child 内容结论（PASS/P0=0）与 Host 终判理由类别。若拒绝理由属于『结论块格式』且与闸自身提示词要求冲突，而内容侧全绿，即可当场裁决缺陷在闸侧而非工件——该判断只依赖回执内已有字段，无需改动任何东西再试错。

## Short path
- 收到 REVISE 先拆回执定侧：child 内容结论字段 vs Host 拒绝理由类别（内容不匹配 / 结论块格式 / 运行失败），此间不修改任何工件
- 若属格式合同自矛盾：定点读该闸的判定源（Host 判定代码/提示词中结论块校验段）一次性确认『判据与提示词互相矛盾』的诊断
- 保持 candidate 材料与 SHA256 完全不变，原样重发同一审查；每轮回执核对 SHA 与首轮一致以证明零改动
- 重跑上限 ≤2 次：通过则按协议继续发布/交付，并在回执与总结中如实记录失败轮 child_id、根因诊断与通过轮终态
- 若矛盾确定性复现或理由转落工件侧，立即停止重跑：保持 BLOCKED 输出具体缺陷证据，另行走演进建议，绝不改工件迎合矛盾判据、绝不绕闸

## Stop conditions
- 任一轮拒绝理由落在工件侧（稿件行与页面正文不一致、配图缺失、指纹不匹配）→ 退出本方法，仅按理由做最小修正
- 同一格式矛盾零改动复现 2 次 → 判定确定性闸缺陷：停止重跑，保持 BLOCKED 并如实上报
- child 内容结论本身非 PASS（存在 P0/P1 或内容缺漏）→ 本方法不适用，回到内容修正路径
- 过闸后必须同时满足 qualification=PASS、P0=P1=0、candidate SHA 与首轮一致，才允许执行发布动作

## Verification
- 逐轮核对 candidate SHA256 与首轮完全一致，证明零改动复用（本集三轮同为同一 candidate SHA）
- 通过轮回执为真实 child 终态（action=status 取到的 completed，而非 wait 计时到点），含 PASS、P0=0、P1=0、指纹一致
- 回执/总结文件同时记录失败轮 child_id、闸侧根因诊断与通过轮终态，且发布动作时间戳晚于过闸时间

## Counterexamples
- REVISE 理由是稿件正文行与页面可见正文不一致、图片缺失等工件侧问题 → 零改动重跑只会重复失败，必须最小修正稿件
- child 结论本身 REVISE/FAIL（内容没过审）→ 不能借『闸有格式矛盾』之名反复重跑碰运气，那等于绕闸
- 闸的判据与提示词一致、只是 reviewer 偶发漏输出某行 → 允许一次零改动重跑，但不应定性为闸缺陷，复现两次即按确定性缺陷收口
