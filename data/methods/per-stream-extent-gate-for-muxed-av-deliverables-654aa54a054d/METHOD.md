---
method_id: per-stream-extent-gate-for-muxed-av-deliverables-654aa54a054d
name: per-stream-extent-gate-for-muxed-av-deliverables
description: 多流媒体成品（视频+配音+配乐+字幕混流）验收时，整体性指标（容器总时长、整片响度/亮度、黑帧统计）在组件被截断或错位时仍会全绿——响度是在存活音频上算的。方法：先用 ffprobe 比对每条流自身 duration 与容器 duration，任一流显著短于容器即否决并回到混音/装配链查时长语义；装配与字幕顺序必须按权威 manifest 切点排序而非并行手工清单；整体指标只作补充。来自本地 H3 短片交付：自验收 -16 LUFS 通过但音轨实际仅 4.49s（约 92.6% 无声），由交付前独立审查抓出。适用面比 H3 短片流水线卡更宽：任何混流 A/V 成品验收。
aliases: 视频验收先查每条流时长, 响度正常但音轨被截断, 成片大部分无声怎么发现, 混流验收看流不看总指标, 字幕和画面不同镜怎么查
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:611007c7-8311-4eb8-896f-2687efc09f46:0:75d09900aef240c19a7f
evidence_refs: learning:learn:2f47479a419f
created_at: 2026-10-26T19:50:24.106822+08:00
updated_at: 2026-10-26T19:50:24.106822+08:00
---
## Trigger
合成多流媒体成品后进入验收，且当前通过判据是整体性指标（总时长、整片响度/亮度、黑帧/平均帧统计），或装配/字幕顺序来自与权威 manifest 并行维护的手工清单时。

## Discriminator
一条命令可读的组件级事实：ffprobe -show_streams 下各流自身 duration 与容器 duration 的对比（如音频 4.49s vs 容器 60.5s 即 FAIL），以及权威 manifest 切点顺序与装配清单顺序的 diff。整体响度/总时长在组件缺失时仍报正常值，不具否决力。

## Short path
- 混流完成后第一检查：ffprobe -show_streams/-show_format，逐流读 duration/nb_frames，与容器总时长比对（容差如 0.1s）；未知量=每个组件是否完整覆盖成品时间轴。
- 任一流时长显著短于容器且非有意留白→判 FAIL，直接回混音/装配链定位时长语义（amix duration、-shortest、apad、清单顺序），不再叠加整体指标自证。
- 流级通过后，按权威 manifest 的切点/时间键排序装配与字幕，抽样首/中/尾核对音画同镜、字幕对齐。
- 最后才跑整体指标（两遍 loudnorm、黑帧、亮度）作补充，不得作为唯一通过判据。
- 交付文件与被审查文件 sha256 一致后停止。

## Stop conditions
- 所有流 duration 与容器一致（或在已声明的有意留白范围内）。
- 抽样分段音画同镜、字幕与台词时间对齐。
- 交付 sha256 与被审 sha256 逐字节一致。

## Verification
- ffprobe 单命令输出各流 duration/nb_frames/codec_type，可脚本断言 min(流时长)/容器时长 ≥ 阈值。
- 对有声段做分段 RMS/响度检查，而非仅整片 loudnorm。
- 权威 manifest 顺序与装配清单顺序 diff 为空。

## Counterexamples
- 有意设计的不等长：片尾音乐淡出早于画面结束、开头留白静默→时长等式不是判据，需意图白名单。
- 单流产物（纯音频/纯图/纯文本）→无跨组件不变量，本方法不适用。
- VFR 或时间基不同的素材→duration 机械比对需先换算，直接等式会误报。
