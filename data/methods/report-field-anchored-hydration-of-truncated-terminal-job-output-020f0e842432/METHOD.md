---
method_id: report-field-anchored-hydration-of-truncated-terminal-job-output-020f0e842432
name: report-field-anchored-hydration-of-truncated-terminal-job-output
description: 门控长任务到达真实终态后，若用户只要特定聚合字段（退出码、各阶段 pass/skip、终判、SHA）而完整输出回执被 range 分窗截断：以『报告字段→最廉价权威来源』驱动水合。退出码直接采信 wait 回执；先水合尾部窗口拿总判、末阶段统计与中途异常处置；每个仍缺失字段只在其 stage 头锚点附近水合一个最大窗口；预览已展示区间视为已读不重取；所有字段各有引证行即停，不为『读全』继续。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:654ef41b-7d98-4c09-af0c-eb47954466a1:0:438348f96c888b543bd3
evidence_refs: learning:learn:242c8ad7a2bf
created_at: 2026-10-21T09:40:47.809159+08:00
updated_at: 2026-10-21T09:40:47.809159+08:00
---
## Trigger
长命令经 wait 达到真实终态（exit 已知），job_output/evidence 回执带 range 元数据（start/next_start/complete）截断完整日志，且任务只需报告特定聚合字段（终态/exit、各阶段 pass/skip、verdict、SHA），而非全文归档。

## Discriminator
水合开始前已可观到的三件事实：(1) 回执预览已展示输出语法——阶段头行（═══ [N/5] …）后紧跟紧凑 verdict/统计行，段间主体是进度点与同质审计告警（『51 处…仅告警不阻断』）；(2) wait 回执本身已载 terminal exit code；(3) 预览窗口已覆盖头部区间。这三点把『677 行未知』缩成『每个缺失报告字段一个小窗口』。

## Short path
- 终态/退出码直接采信 wait 回执（job_terminal, exit=N），不重查。
- 调一次 job_output 取 blob 句柄与预览；把预览已显示的范围标记为已读（头部各阶段统计通常已在其中）。
- 先水合尾部窗口：总判行、末阶段统计、以及中途异常（如 tier0 出现 1 failed 但 exit=0）的处置段（serial 复核结果）。
- 对每个仍未落实的报告字段，从其 stage 头/首个未覆盖锚点起，用 range 服务器允许的最大窗口水合一次，不跳过未覆盖间隙、不回读已知噪声区。
- 所有字段各有可引证行后立即停止水合并撰写报告：每个数字标注来源行/区间；未观测到的统计明确说明未观测。

## Stop conditions
- 用户要求的每个字段（终态/exit、指定范围 pass/skip、verdict、SHA）都能指认一条已观测来源行。
- 出现未解释异常（mid-output failed 但 exit=0 且尾部无处置行）时，只追加围绕该异常锚点的一个窗口，读到处置或确认无处置即停。
- 不因『日志尚未读全』继续水合——除非用户明确要求全文。

## Verification
- 报告中每个数字可映射到某条已显示的 stdout 行（或带 range_sha256 的水合区间），无凭记忆推断的统计。
- exit code 同时出现在 wait 回执与 job_output 终态且一致。
- 中途失败要么有观测到的复核/处置行支撑结论，要么如实报告为未解释，不得静默丢弃。

## Counterexamples
- 用户明确要求完整日志归档或粘贴全文：全覆盖水合本身即需求，字段驱动不适用。
- exit≠0 或结果异常：根因 traceback 可能藏在与噪声同形的区段，应沿失败锚点（traceback/failed 行名）追踪，而非只读各阶段摘要行。
- 输出无阶段头语法、目标统计位置未知：锚点无立足点，用最大窗口顺序覆盖、字段齐备即早停即可。
- 短输出一窗可容纳：直接整读，无需锚点策略。
