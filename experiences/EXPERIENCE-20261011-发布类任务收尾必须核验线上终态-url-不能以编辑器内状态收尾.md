---
title: 发布类任务收尾必须核验线上终态 URL，不能以编辑器内状态收尾
scenario: "通过浏览器自动化在第三方内容平台（知乎专栏 / 今日头条等）发布长文；跨会话继续同一推广 Goal，某个\"发布\"任务因编辑器交互受阻（Draft.js 字数计数器死锁）被记录为未完成并长期挂在任务图 ready 状态。"
root_cause: "把\"编辑器内计数器卡住\"这一中间态直接写成了\"未发成功\"的终态结论，且该结论未在收尾时抓一次线上 URL 复核；同时上一次会话结束后到本轮生成之间该发布动作已完成，导致一个实际已完成的任务在任务图里长期挂着 ready，掩盖了真实状态并诱发\"需要绕过计数器\"的错误后续计划。"
solution: "发布类动作的完成判定必须是\"线上资源终态\"，不是编辑器内状态。具体：1) 抓取目标平台文章 URL 的线上页面，提取 datePublished/dateModified，与本轮时间线对比——若 datePublished 晚于上次会话记录的\"失败\"时刻，说明发布动作已在别处完成，任务的真实阻塞点是核验缺失，不是发布失败；2) 核验用行级 diff（正文行数/章节标题/字数）而非目测，并把\"本地稿与线上稿不一致\"区分为缺失(需补)与线上更新(本地过时，无需改)；3) 图片数量以 data-original/src 指向的真实 URL 判定，class 含 lazy 的占位图须单独 curl HEAD 确认可达，懒加载占位不等于缺图；4) 恢复上下文时按权威度分层：对话记忆(最低) < 持久记录(对\"发生过什么\"权威，但对外部可变状态只是快照) < 目标系统新鲜观察(当前态唯一权威)。记录时间戳早于当前且资源存在已知写者时，必须升级到新鲜观察再对现状下断言。"
evidence: "本轮实测：线上 https://zhuanlan.zhihu.com/p/2092334918437230422 的 datePublished=2026-10-10T11:29:04Z(北京时间19:29) 晚于上次会话 19:26 的\"未发成功\"判定，证明发布在收尾后已完成；行级 diff 显示线上95/96行、12章节、9433字、4图全部可加载，与本地 d3.html 的5处差异均为线上更新(805测试/27条RULE-AI/v0.6.28/main@692aef75时点快照)而非缺失；第4张图 class 含 lazy 为懒加载占位，data-original 的 curl 返回 200/51KB，非缺图。"
tags: [verification, publishing, cross-session-resume, evidence-tiers, task-graph-hygiene, browser-automation]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-11T00:20:00.729327+08:00"
updated_at: "2026-10-11T00:20:00.729327+08:00"
---