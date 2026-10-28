---
method_id: same-layer-hash-baseline-when-admission-sha-differs-from-patch-sha-ad3016383381
name: same-layer-hash-baseline-when-admission-sha-differs-from-patch-sha
description: 准入/审查类闸门的 start 回执返回的 admission 层 candidate_sha256，与任务书冻结的 patch 层 SHA256 是两个不同对象，跨层不一致本身不是漂移。以 start 回执的同层哈希为漂移基线：pending 期间做有界等待+status 轮询（单次上限报错后钳到边界值）；首个非 pending 终态回执核对 SHA 与基线逐字节一致，逐字引用 verdict/计数、不臆测缺失片段，按契约立即停止，修复与重交留给用户。
aliases: 审查回执哈希和补丁哈希不一致算漂移吗, 准入返回的SHA跟冻结patch SHA不一样, start和status哈希怎么核对, 两个SHA什么时候必须一致, 准入闸误报漂移
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e82c75b1-a2da-409d-9a7f-a9ac72de3fd5:0:91259e0e087b291b7730
evidence_refs: learning:learn:880796f3f47f
created_at: 2026-10-25T23:19:23.333298+08:00
updated_at: 2026-10-25T23:19:23.333298+08:00
---
## Trigger
闸门流程要求『发生漂移/拒绝立即停』：准入工具（review_admission 类）start 成功回执带 accepted 与 candidate_sha256，而任务书另行冻结了 patch SHA256/tree 哈希，且两哈希不相等

## Discriminator
两个哈希来自不同层：任务书冻结内容层（patch 字节），start 回执冻结准入材料层（包裹 workdir+command 的资格对象）。漂移定义为同一层回执哈希在 start 与 status 之间发生变化；跨层不匹配不是停止信号

## Short path
- start 成功后记录 child_id 与 candidate_sha256 作为同层漂移基线，明确标注『与 patch SHA 是不同对象』，不尝试对齐或重新冻结
- status 回执为 pending 期间继续有界等待；等待参数超上限报错时，直接改用报错回执揭示的边界值（如 120s），不再试第三个值
- 首个非 pending 终态回执：核对其 SHA256 与 start 基线逐字节一致→无漂移；逐字引用 qualification/reason/P0P1P2 计数，不从尾部片段推测缺失的 P1 细节
- verdict 为显式非 PASS（如带计数的 VERDICT 行）→按契约立即停止：不补救、不重交、不改任何状态，只如实报告
- 仅当同层回执哈希真正变化、或工具约定明确要求回显 patch SHA 时，才判定漂移→停下并上报

## Stop conditions
- 终态 qualification 为显式非 PASS 且回执 SHA 与 start 基线逐字节一致→报告后停止，修复/重交交由用户决定
- 同层回执哈希变化、或准入槽位被填入 patch 层哈希→按漂移上报并停止
- 终态回执无可解析的 VERDICT/计数字段、仅有模糊 reason→不适用本卡『逐字引用即停』，先查 child 原始输出裁决真实结论

## Verification
- status 终态回执 SHA256 与 start 回执 candidate_sha256 逐字节一致
- verdict 与 P0/P1/P2 计数逐字来自回执字段或 VERDICT 行，无自行编造的问题描述
- 终态回执之后除报告外无任何工具调用，无文件/提交/发布等状态变更

## Counterexamples
- 闸门约定明确承诺 status 必须回显任务书冻结的 patch SHA→跨层不一致即真漂移，应停止上报
- 中途某次 status 的同层哈希发生变化→真漂移而非分层差异，立即停
- 同步工具一次调用即返 verdict→无需 wait+status 循环，直接验证
- 任务书只给一个哈希且要求严格相等、无准入包裹层概念→按任务书直接做相等校验
