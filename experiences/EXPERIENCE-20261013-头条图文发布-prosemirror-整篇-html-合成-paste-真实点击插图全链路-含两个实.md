---
title: 头条图文发布：ProseMirror 整篇 HTML 合成 paste + 真实点击插图全链路（含两个实测踩坑）
scenario: 在已登录的今日头条创作者后台（mp.toutiao.com/profile_v4/graphic/publish）把一篇本地 Markdown 稿件发布为图文。编辑器是 ProseMirror，工具栏按钮无 tooltip。
root_cause: 编辑器为 ProseMirror，DOM Range/execCommand delete 无法删除平台 card 节点；DOM.setFileInputFiles 对不存在路径静默不报错，只在面板里留「上传失败」。
solution: "流程：①标题用 HTMLTextAreaElement.prototype.value 原型 setter 写入 + input 事件；②正文整篇 HTML 一次 ClipboardEvent paste（text/html + text/plain 双通道），表格/引用/强调一次成型，平台会把 h2 归一为 H1，无需对抗；③插图先 scrollIntoView({block:'center'}) 再用 Input.dispatchMouseEvent 真实点击目标标题行定位光标 → 点 .syl-toolbar-tool.image .syl-toolbar-button → DOM.setFileInputFiles → 删掉 .pic-select-image-item .error 失败项 → 点「确定」；④作品声明勾 label.checkbox-with-tip 内 innerText 为「引用AI」的 input（value=3）；⑤「预览并发布」→「确认发布」。两个实测坑：文件路径必须用 os.path.abspath(\"img/x.png\") 相对 cwd，os.path.dirname(abspath(\".\")) 得到的是父目录会拼出错误路径导致上传失败且失败项会混进正文；平台自带首图卡片 syl-selected-card（contenteditable=false）删不掉，只能接受其位置。"
evidence: "docs/promotion/receipts/20261013-daily13-toutiao.json 与 docs/promotion/STATUS-20261013.md（2026-10-13 头条第13期实际走通，11:15 提交审核中，正文3059字+2图+引用AI）"
tags: [头条, 发布, CDP, ProseMirror, 上传, 发布链路]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T11:19:09.636454+08:00"
updated_at: "2026-10-13T11:19:09.636454+08:00"
---