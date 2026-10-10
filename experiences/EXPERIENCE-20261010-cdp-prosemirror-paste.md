---
title: 今日头条网页版图文发布全链路：CDP 直连 + ProseMirror paste 注入
scenario: 通过 CDP 直连操作已登录的今日头条网页版编辑器，发布图文长文
root_cause: ""
solution: "用 execute_command + Python websockets 连 127.0.0.1:9229 的 CDP，绕开 browser_operate 的语义定位限制；正文用 paste 事件注入 HTML，图片用 DOM.setFileInputFiles + 点\"确定\"插入，插图定位用 setStartBefore(段落锚点) 避免空标题残留，图片描述用 Input.insertText 持久化"
evidence: "evidence://v1/47161dc69292f69b88126949b67ba25cdcba9ac940bf46adb5218c091763bf4b (execute_command _verify.py：作品管理页 article-card 确认标题+审核中+pgc_id=7694948729350111759)；evidence://v1/198232aa7b144e4b1dcb8a04cdc59497e0435ae249bb7a8b052d7c1945158d45 (execute_command _topub.py：预览页 descs=5/coverMode=multi/words=5071 校验)；evidence://v1/085d3b32048adee5f2053f25741ad9db0af113cc04dbee2eb8726e54f437949b (execute_command _publish.py：确认发布并跳转作品管理页)"
tags: [今日头条, CDP, ProseMirror, 浏览器自动化, 图文发布]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-10T16:27:25.015671+08:00"
updated_at: "2026-10-10T16:27:25.015671+08:00"
---

目标：在已登录的今日头条网页版（mp.toutiao.com）发布一篇带自制插图的 Markdown 长文。

关键发现（均为实测）：
1. 编辑器是 syllepsis 封装 ProseMirror（.ProseMirror[contenteditable]），标题是 textarea[placeholder*="标题"]，上限 30 字。
2. 工具栏按钮 class=.syl-toolbar-button 且**无可访问名**，browser_operate 语义定位点不到，需 CDP 直连。
3. 图片上传：点击第 12 个 toolbar 按钮 → 动态创建 input[type=file].btn-upload-handle → CDP DOM.setFileInputFiles → 面板显示"已上传 N 张" → 点"确定"按钮才真正插入编辑器。仅 setFileInputFiles 不点确定不会插入。
4. 正文注入：CDP Input.dispatchKeyEvent 的 Cmd+V **不生效**（粘贴属浏览器 UI 层）。有效方式是 Runtime.evaluate 构造 DataTransfer 并 dispatchEvent(new ClipboardEvent('paste'))，ProseMirror 会正确解析。
5. 内容映射：h1/h2/h3 全部塌缩成同一级 h1；table/pre/code/ol/ul/strong/blockquote 保留；<a href> 被剥离成纯文字；<th> 降级为 <td>。故三级标题应用 <p><strong> 表达。
6. 清空编辑器必须用原生 Delete 键（Input.dispatchKeyEvent key=Delete + selectNodeContents）；全选+粘贴在经历面板交互后退化为追加而非替换。

三个真实陷阱：
A. 外部设置的 DOM Selection 在面板交互后不再被 ProseMirror 感知，"全选→粘贴"会变成追加。
B. 用 r.setStartAfter(node) 定位插图会残留空 <h1><br></h1> 占位节点（会被头条渲染成空白大标题行）。改成 setStartBefore(段落) 可避免；若已产生，清理时若空 h1 前一个兄弟是图片容器 DIV，Backspace 会把图一起合并删掉，需改用 Delete。
C. 图片描述用原生 setter+input 事件填，退出预览层后会被草稿重载清空。必须用 CDP Input.insertText 配合 focus/Tab 走真实输入路径才会持久化。

收口校验：字数(共 N 字)、.ProseMirror img 数、空 h1 数、描述框非空数、标题计数 N/30、发布后作品管理页 article-card 出现标题+审核中。