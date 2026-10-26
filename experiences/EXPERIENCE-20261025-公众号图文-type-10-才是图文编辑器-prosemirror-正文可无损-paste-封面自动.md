---
title: 公众号图文：type=10 才是图文编辑器、ProseMirror 正文可无损 paste、封面自动化设不上（发表被平台校验阻断）
scenario: 微信公众号图文编辑器（mp.weixin.qq.com/cgi-bin/appmsg）自动化发一篇长文（表格 + 首图）
root_cause: ""
solution: |
  ① 新版图文编辑器 URL 必须带 type=10（不带会落到「编辑商品消息」，页面里根本没有正文编辑器，只有标题/作者/封面/描述表单）；② 有效会话要自己探：mp.weixin.qq.com 有多个 tab，老 token 会「登录超时」，逐 tab 用 CDP 探活后选有效 token（本次有效 73454389）；③ 正文编辑器是 .ProseMirror（选 `#js_editor .ProseMirror`），标题也是 ProseMirror（按 placeholder 含「标题」区分）；正文一次 paste 用 ClipboardEvent('paste') 带 text/html+text/plain 投递到 focus 后的正文 ProseMirror，粘贴后与 wx.html 的纯文本渲染归一化比对可到 ratio=1.000；标题用 Input.insertText 写入（注意 insertText 会落到当前焦点元素，别先点正文）；④ 封面自动化设不上（本次 6 路径全失败：file input 直塞→图进素材库且落到正文、从图片库选择→下一步+确认无效、从正文选择→无可选缩略图、drag drop→无效、一键生成封面→入口不可点），平台校验「必须插入一张封面图片」把「发表」按钮置灰 → 这一步需要人工点一次；⑤ 草稿先「保存为草稿」可拿到 appmsgid，便于回读与续做。
  当前性验证：跑 `curl -s http://127.0.0.1:9229/json | grep -o '"url": "[^"]*mp.weixin[^"]*"'` 看是否还有带 type=10/token 的编辑器 tab；对该 tab 跑 _cdp_eval.py 读 .setting-group__cover 的 innerText，含「拖拽或选择封面」即封面仍未置上。
evidence: "evidence://v1/da43b0c1c738fb5c92f89d90b92af210fdd5e23dd7814152b2b406105a8bea80, evidence://v1/d927d1403e86afc6d9c5c1d16f81f619d5e2873cc8897cf9c6071970a98ac99d, evidence://v1/68c580afe37a824c444b1bc1b7aa7da16922de313956feeab3512c27ca3d3f95"
tags: [公众号, weixin, 发布, 封面, ProseMirror, type=10]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-25T14:46:42.930364+08:00"
updated_at: "2026-10-25T14:46:42.930364+08:00"
supersedes: [EXPERIENCE-20261020-公众号图文编辑器-正文一次-paste-图注段落-home-落光标插图可自动化-backspace, EXPERIENCE-20261025-知乎专栏发稿链路-reload-才同步应用态-clear-paste-会翻倍-话题框会污染正文-发布]
---