---
title: 头条编辑器用 ClipboardEvent 注入图片会清空正文：必须用段落文本节点内的折叠光标，且粘贴前断言选区为空
scenario: 在今日头条文章编辑器（mp.toutiao.com/profile_v4/graphic/publish）里，用 ClipboardEvent('paste') 向 DataTransfer 放入 image/png File 来插图。若选区不是折叠光标而是选中文本（尤其全选态），图片节点会替换整篇正文：正文整段消失，只剩图片卡，页脚字数变「共 0 字」，且标题不受影响。该问题可复现，且不会报错——页面上没有任何错误提示，误判为「粘贴失败」会反复重试浪费大量时间。
root_cause: ""
solution: |
  光标必须落在段落【文本节点内】并折叠，不能用段落【边界】：
  - 错误：r.setStartBefore(para); r.setEndBefore(para)
  - 正确：const node = para.firstChild || para; r.setStart(node,0); r.setEnd(node,0)
  
  并加两道闸：
  1) 粘贴前硬断言：const sel=window.getSelection(); if(sel.toString().length!==0) return 'ABORT' —— 选区非空就拒绝粘贴，不要硬来。
  2) 每插一张图后 sleep 8~10s 复验 pm.innerText 去掉空白后的字数是否塌陷，确认正文还在再插下一张。
  
  注意 pm.focus() 必须放在 addRange 之后（本例中 focus 未破坏折叠选区），但仍要以上面的断言为准。诊断时用 Page.captureScreenshot 比读 DOM 更快定位——页脚「共 0 字」是正文被清空的直接信号。
evidence: 第 9 期 20261011-lfl-daily-09 发布现场：错误写法下 paras 73→4、chars 3434→4 复现 3 次；改为折叠文本节点光标 + ABORT 断言后，chars 3434→3438→3442 稳定，正文完好，两图均成功插入并加载（1000x500 / 1000x520），发布后 PGC 7695406258093818408 审核中。第 8 期因未加断言即连续三张批量插入，也曾触发同一清空（paras 62→4），恢复后重做。
tags: [browser, cdp, toutiao, clipboard, prosemirror, 发布流水线, 选区, 数据破坏]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-11T21:47:52.629487+08:00"
updated_at: "2026-10-11T21:47:52.629487+08:00"
---