---
method_id: audit-img-load-state-via-dom-before-viewport-scroll-quests-f5cc13bd72b0
name: audit-img-load-state-via-dom-before-viewport-scroll-quests
description: 发布闸要求核对『N 张配图真实加载且互不相同』、而当前视口看不到图时，不要靠滚动视口+反复快照去碰运气找图：先用一次 DOM eval 收集预览容器内每张 img 的 currentSrc/naturalWidth/rect——naturalWidth>0 且 currentSrc 非空即真实加载，src 哈希前缀即互异性，rect 即精确滚动锚点；如还要求视觉证据，再按锚点逐图滚入视口各截一张。把『看不见图→盲滚取证』缩为『逐图状态清单→定点取证』，避免整页翻滚、旧投影 grounding 失败和事后回读稿件找图位。
aliases: 配图加载核验, 预览图懒加载排查, 滚动半天找不到图, 发布前图片QA, 裂图检查, 编辑器配图取证
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5ba33822-1ffd-405b-b3b4-33013b320dda:87:b3aecd233b189d3aa961
evidence_refs: learning:learn:d185ecdf3ea8
created_at: 2026-11-11T16:03:33.862331+08:00
updated_at: 2026-11-11T16:03:33.862331+08:00
---
## Trigger
发布前 QA/审查闸要求确认编辑器或预览面板中 N 张图『真实加载』（而非仅存在于 DOM），DOM 计数已给出 imgs:N 但视口当前看不到图；或曾在其它平台见过 lazy 图 DOM 在而未加载（currentSrc 空、naturalWidth=0）的先例。

## Discriminator
对预览容器做单次 eval 即可得到每张 img 的 {currentSrc, naturalWidth, getBoundingClientRect}：加载成功=naturalWidth>0 且 currentSrc 非空；互异=src 前缀哈希两两不同；同一批 rect 直接给出视觉取证所需的精确滚动锚点——图片位置信息本来就在 DOM 里，无需盲滚视口或回读稿件来发现。

## Short path
- 文本级 QA（标题、稿件行覆盖、AI 声明）通过后，把剩余未知量收窄为『每张图是否真实加载且互不相同』
- 对预览容器一次 DOM eval，输出全部 img 的 currentSrc/naturalWidth/rect，先机械判定 loaded 与 distinct
- 若流程另要求视觉渲染证据，用 rect/scrollIntoView 把每张图精确滚入视口，每图一次截图（锚定元素本身，不做整页翻滚或凭标题估算滚动量）
- 发现未加载图（currentSrc 空/naturalWidth=0）时只修复并复测该图，不重扫全部图片
- 逐图证据齐备后立即进入下一闸（如 Host review），不再追加『再确认』快照

## Stop conditions
- 每张图 naturalWidth>0、src 前缀互异（或与上传回执的 CDN 哈希一致），且如需视觉证据则每图已有一张渲染截图
- 任一图确定性未加载且修复超出当前授权（需重传/改稿）→ 停止取证并上报，而不是继续滚动快照

## Verification
- 视觉截图中可见图像张数 = DOM 报告的 loaded 图数，无空白占位框/裂图
- 记录逐图 src 哈希前缀清单，与稿件/上传回执中的图 URL 一一对应

## Counterexamples
- 用户只要求『图已插入正文』而不要求加载成功：DOM 计数即可停止，逐图 eval 与截图属过度实施
- 图片渲染在 iframe 或跨 context：主 frame eval 取不到节点，须先定位 frame，本方法不适用
- 目标是公网匿名视角的图片可达性核验：应在发布后的公开 canonical URL 上做，而非编辑器预览
- 图为 CSS background 或 canvas 绘制而非 <img>：currentSrc/naturalWidth 不可用
