---
method_id: verbatim-anchor-search-then-window-hydration-for-truncated-job-logs-2e2f455db968
name: verbatim-anchor-search-then-window-hydration-for-truncated-job-logs
description: 把截断任务日志 evidence blob 的读取从顺序分页改成锚点索引：只用已在回执里逐字见过的唯一锚点（阶段标记、已见汇总行、末行✅）去检索，按命中偏移开窄窗水合确认裁决行；自造措辞的检索 miss 应读作查询错误（零缺失信息），不连发换措辞猜测、也不退回整本顺序翻页穿过同构告警噪声。本集把约15+次分页加3次无效措辞搜索压成约6-7次定向调用。
aliases: 长日志别整本翻，用已见原句当搜索锚点, 截断CI输出先搜阶段标记再开窗读, 检索未命中先怀疑查询措辞而非内容缺失, 按match_char偏移窄窗水合, job日志跳过告警噪声直取结论行
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ba93f6f2-47ca-440c-bc17-ae49e9ceef61:24:366cd17d695344f1056f
evidence_refs: learning:learn:0e06dbc60356
created_at: 2026-10-24T07:21:55.727490+08:00
updated_at: 2026-10-24T07:21:55.727490+08:00
---
## Trigger
大体积被截断的任务日志（CI门禁/全量测试输出）以 durable evidence blob 按字符区间分块水合，且会话提供对该 blob 的逐字子串检索（回执含命中片段与 match_char 偏移）；用户只需少数裁决性行（各阶段结果、exit码、汇总统计），而 blob 中段是大段同构告警/审计数组。

## Discriminator
早前检索命中或首块水合里已出现可逐字复制的唯一锚点：阶段标记（如 [1/5]/[5/5] 分节头）、已见汇总行（如 '319 passed, … in 24.72s'）、末行 ✅ 总结；且回执格式证明检索是逐字匹配并给出偏移。这已把『答案在哪』从整本627行缩成几个可开窗验证的坐标。

## Short path
- 按回执点名调用 wait/job_output 取 terminal 状态、exit 码与分页元数据（627行、4000字/块）
- 列出仍缺的裁决行（各阶段 verdict、全量 pytest 统计），对每个未知量选一个已见逐字锚点：阶段标记、已见 summary 片段、末行 ✅
- 用这些锚点做逐字检索，取得各自 match_char 偏移；全量统计通常紧邻末行 ✅ 之前
- 只对各偏移开窄窗水合（如 start=偏移±200、limit≈800）逐字取裁决行；不进入告警数组区间
- exit码与全部所需行均逐字取得且属于同一 blob_sha256 即停止；检索 miss 只说明措辞不符，改锚点而非换措辞重猜

## Stop conditions
- 用户点名的 exit 码、每一阶段结果、汇总统计均已从同一 evidence ref 的水合窗口逐字取得
- 或已水合到 complete:true 仍无锚点命中，才允许下『不存在』结论（受 partial-coverage 门控）

## Verification
- 每条对外引用的统计/verdict 行逐字出现在同一 blob（blob_sha256 一致）的某个水合窗口内
- 阶段计数与日志自声明结构一致（如 N/5），末行总结与首行 exit 码互相印证

## Counterexamples
- 会话没有对该 blob 的逐字检索面（只能 range 水合）时不适用，退回『跳过同构数组+尾部探针』路径
- 用户问题本身是穷尽性的（如逐条复核全部 51 条 base_url 告警是否高风险），顺序全读就是任务，跳噪会漏答
- 锚点标记在嵌套输出中不唯一、或检索是模糊排序而非逐字匹配时，偏移不可靠，miss 也不再具有『措辞错误』的强判读
