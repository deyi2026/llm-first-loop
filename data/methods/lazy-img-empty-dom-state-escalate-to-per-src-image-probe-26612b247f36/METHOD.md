---
method_id: lazy-img-empty-dom-state-escalate-to-per-src-image-probe-26612b247f36
name: lazy-img-empty-dom-state-escalate-to-per-src-image-probe
description: 发布/验收闸需判定『N 张配图可加载且互不相同』，而已有 DOM 证据是 img 带 loading=lazy、currentSrc=''、naturalWidth=0（整页重载后或图在视口外）时，这组空值是惰性加载未触发的默认态，不是坏图证据；不要据此维持 BLOCKED，也不要继续滚动试探、反复重载或在页面上下文外探测签名 URL。在已认证页面内对每个图源各跑一次 new Image()，以 load/error 与 naturalWidth 做二元裁决：全部 load 且 src 唯一即可加载性成立；任一 error 或 naturalWidth=0 维持 BLOCKED。定位为『先 DOM eval 后滚动试探』方法的下一跳：当 DOM eval 返回空值且带 lazy 属性时，升级为程序化逐源加载探测。
aliases: 图片重载后不显示是不是懒加载没触发, currentSrc 为空等于图挂了吗, naturalWidth 0 懒加载假阴性, 配图只允许探测一次怎么判好坏, 编辑器空占位图最小核验, 签名图 403 换页面内 Image 探测
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:5ba33822-1ffd-405b-b3b4-33013b320dda:429:9c739d5e39dae45538e5
evidence_refs: learning:learn:2020780af1b3
created_at: 2026-11-11T17:08:42.213616+08:00
updated_at: 2026-11-11T17:08:42.213616+08:00
---
## Trigger
发布闸/验收要求核验配图真实可加载（加载成功、自然尺寸正常、互不相同），而已观察到的 DOM 状态是 img 元素带 loading=lazy 且 currentSrc 为空、naturalWidth=0（重载后或图在视口外），据此曾判定或倾向判定『渲染异常/缺图风险』

## Discriminator
img 带 loading=lazy 且未与视口相交 ⇒ currentSrc 空与 naturalWidth=0 是未触发加载的预期表现而非加载失败；同时上传回执已给出各图成功 token/指纹，剩余唯一未知量收窄为『每个图源能否加载出 naturalWidth>0』，这与『编辑器内是否可见渲染』是两个不同问题

## Short path
- 把未知量从『编辑器为何不显示图』改写为『每个已上传图源能否加载出 naturalWidth>0 且 src 互不相同』
- 在已认证/已登录页面上下文内执行一次最小脚本：对每张图的 src 各 new Image()，收集 load/error、naturalWidth×naturalHeight、src 去重结果
- 全部 load 且 naturalWidth>0、src 唯一 ⇒ 可加载性成立，缺图/BLOCKED 前提失效，按正常准入闸继续发布路径
- 任一 error 或 naturalWidth=0 ⇒ 维持 BLOCKED 并停止，不追加第二轮探测、不做视口滚动试探、不在页面外用无凭证请求碰签名 URL

## Stop conditions
- 每图 Image() 均得到确定性 load(naturalWidth>0) 或 error 结果即停，探测结果就是终局裁决
- 指令限定『只允许一次最小网络探测』时，单脚本一次覆盖全部图源即预算用尽，不得拆成多轮
- 可加载性结论已与上传回执 token/指纹一一对应后，不再为『编辑器内可见性』追加网络探测（那是渲染层问题，另行核验）

## Verification
- 各图 load 回执的 naturalWidth/naturalHeight 数值合理且非零，四个 src/token 互不相同
- 探测得到的图源与上传回执中的 token/指纹一一对应，无冒充占位图
- 若据此放行发布，发布后公网回读逐图确认真实渲染（可见性/位置），与可加载性结论分层记录

## Counterexamples
- 图源真实失效或签名过期：Image() 触发 error 或 naturalWidth=0，方法正确维持 BLOCKED，不得用『lazy 解释』强行放行
- img 无 lazy 属性、已在视口内且 naturalWidth>0：DOM 状态本身已充分，无需程序化探测
- 闸要求的是成文版式中图的渲染位置/几何而非可加载性：Image() 探测不覆盖该判据，需渲染几何核验
- 在页面上下文之外（shell/curl/无凭证环境）探测需 referer/cookie 的签名 URL：会因 403 假阴性误判坏图，探测必须跑在已认证页面内
