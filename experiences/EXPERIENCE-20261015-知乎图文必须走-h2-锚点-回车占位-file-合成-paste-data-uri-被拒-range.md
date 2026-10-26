---
title: 知乎图文必须走「H2 锚点 + 回车占位 + File 合成 paste」：data-URI 被拒、Range 光标无效、删标记会吞段落
scenario: 在知乎专栏编辑器（Draft.js，zhuanlan.zhihu.com/write）为一篇 6 图长文完成插图并发布。上一轮经验卡的 data-URI 方案在头条验证通过，本次直接套用到知乎后被平台拒绝。
root_cause: "三处独立机制：(1) 知乎不接受 data:image/png;base64 内嵌图，统一替换成 240x120 的失败占位并提示「图片导入失败，请重新上传」——240x120 是占位尺寸而非缩略图，不能当作『已上传』的判据；(2) Draft.js 不认 Range/Selection 造出的程序化光标，File 合成 paste 会被当成『追加』，6 张图全堆到文末；(3) 事后删除标记文本时 BlockTree 合并会连带吞掉相邻正文段落（实测吞掉 §五 首段『我特意把边界写清楚…』）。"
solution: |
  可用链路（2026-10-15 实跑，公网回读通过）：正文 HTML 转换时**同时剔除图片与标记** → 贴入并清空（Range.selectNodeContents + 真实 Backspace 循环到空，合成 execCommand('delete') 会残留半截文本）→ 逐张：定位各 H2 标题块之后的首个兄弟块，点击其**行首**（x=left+3）建立真实光标 → 派发 Enter 键事件腾出一个空块 → 点该空块 → 向 [contenteditable=true] 派发携带 image/png File 的 ClipboardEvent('paste')。图序天然正确（按标题从上到下），全程无标记、无删除动作。AI 声明：点「无声明」开 Select 弹层，选项是带子 span 的 Select-option（用 children.length===0 过滤会漏掉），选「包含 AI 辅助创作」；选项列表需 POST 才有数据。
  
  度量纪律：图片唯一性按 img.currentSrc 判；插图位置用 getBoundingClientRect().top 与各 H2 的 top 对比，这是唯一能识破『图全被追加到文末』的检查——只数图数会得到 6/6 的假通过。
evidence: "知乎公网 https://zhuanlan.zhihu.com/p/2094109213794512935 回读：h1=1/h2=6/图 6 张 pic.zhimg.com，9 个关键串 0 缺失，ContentItem-time 显示「编辑于 2026-10-15 17:01 · 包含 AI 辅助创作」；发稿前无损对照 78 行 0 缺失/图 6 唯一且图序正确 exit=0。回执 docs/promotion/receipts/20261015-lfl-memory-zhihu.json。反例日志：data-URI 方案 6 图全为同一 240x120 占位；Range 光标方案 6 图 y=5567-7949 全在最后标题 y=4690 之后；删标记方案 §五 首段消失致 1 行缺失。"
tags: [知乎, Draft.js, 插图, CDP, 发布链路, 反向经验]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-15T17:07:19.728791+08:00"
updated_at: "2026-10-15T17:07:19.728791+08:00"
supersedes: [EXPERIENCE-20261013-程序化-range-选择不被两端编辑器采纳-cmd-z-在知乎无效]
---