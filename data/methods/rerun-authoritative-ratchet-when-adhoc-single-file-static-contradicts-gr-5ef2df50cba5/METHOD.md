---
method_id: rerun-authoritative-ratchet-when-adhoc-single-file-static-contradicts-gr-5ef2df50cba5
name: rerun-authoritative-ratchet-when-adhoc-single-file-static-contradicts-green-receipt
description: 裸跑单文件静态分析（pyright/mypy 等，不加载项目 venv/ratchet 配置）报出一批错误、看似将阻断门禁，而本树已持有项目级 ratchet 同基准绿回执（new=0）时，不要进入修复模式。阻断与否只由门禁对应步骤的『同一调用方式重跑』裁决：ratchet new=0 → 判定为缺上下文伪报，继续走链；new>0 → 才窄修复。防止幻影缺陷驱动提交、打翻已冻结的审查指纹，触发复审+再准入+再全量门禁的成本翻倍。
aliases: 单文件 pyright 报红算不算门禁阻断, 裸 lint 报错但项目 ratchet 绿信哪个, 静态检查伪报先别急着修, 类型检查器单文件输出和 ratchet 回执矛盾, mypy 单文件一堆错但 new=0
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:80f5e2cd-19c2-42bb-8bca-1c0a01cc2a48:2927:ea7875a0ebcc350bd33f
evidence_refs: learning:learn:eb99406ca518
created_at: 2026-10-25T14:27:44.432287+08:00
updated_at: 2026-10-25T14:27:44.432287+08:00
---
## Trigger
修复/新增代码提交后，出于谨慎或习惯性核验而裸跑单文件静态分析，输出一批错误；同时本项目该分析器的门禁判据定义为项目级 ratchet（new/touched 计数），且本树已有同基准绿回执

## Discriminator
惊吓时刻已在手的事实：(1) 门禁步骤判据是『项目级 ratchet new=0』而非『单文件 0 错』；(2) 同一代码基线的前一轮整树 ratchet 绿回执仍有效；(3) 裸单文件调用未加载项目环境/配置/stub，与门禁调用方法论不同。输出与既有绿回执的矛盾本身指向方法论错配而非新缺陷，把『逐个修 7 个错』缩成『用权威调用跑一次做归类』

## Short path
- 先问判据：该分析器在门禁里的实际阻断判据与调用是什么（从门禁链定义/回执已知），而不是『这 7 个错怎么修』
- 用与门禁完全相同的调用（项目级 ratchet、同配置/路径）重跑，范围覆盖涉事文件/本树
- 按裁决分支：new=0 → 裸跑输出归类为缺上下文伪报，零新提交，继续审查/准入/门禁链；new>0 → 真问题，窄范围修复
- 任何修复提交先过同一 ratchet 复核绿，再冻结指纹/进审查，避免再造一轮复审+再准入+再全量

## Stop conditions
- 权威同调用重跑裁决已取得并与阻断判据对齐；停止对同一文件追加新诊断变体（换配置/换分析器裸跑）
- 确认该文件不在 ratchet 覆盖路径集内时，ratchet 绿不构成对该文件的证据，停止用其dismiss，改走补证路径

## Verification
- 重跑调用与门禁对应步骤在配置/路径/ratchet 包装上逐项一致，而非相似变体
- 裸跑报的错误类别若属 ratchet 可见类别，ratchet 必须同步翻红；两处皆绿一致才下伪报结论
- 若 ratchet 是 new-only（基线差分），确认报错代码段是已登记存量红还是新代码，两者处置不同

## Counterexamples
- 首次接触该代码库、无项目级同基准绿回执 → 裸跑输出是唯一信号，不能判伪报，应先定位权威调用方式
- 涉事文件被 ratchet 路径排除或属 changed-file 跟踪盲区 → ratchet 绿不覆盖此文件，单文件错误可能是真缺陷
- 门禁判据本身就是逐文件检查（部分 lint 配置强制 per-file 干净）→ 裸跑即权威，结论反转
- 错误属静态 ratchet 结构性看不到的类别（运行期类型、行为回归）→ 须以测试/动态验证裁决
