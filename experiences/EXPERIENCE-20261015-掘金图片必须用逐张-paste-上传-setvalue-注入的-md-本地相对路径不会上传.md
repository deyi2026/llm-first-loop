---
title: 掘金图片必须用逐张 paste 上传；setValue 注入的 md 本地相对路径不会上传
scenario: "掘金发布 markdown 文章，正文里是 ![...](imgs/xxx.png) 本地相对路径。"
root_cause: ""
solution: |
  掘金 CodeMirror 的 setValue 只写文本，不会触发图片上传，线上会变成不可访问的相对路径。
  正确链路（已验证）：
  1. 新建草稿：navigate https://juejin.cn/editor/drafts/new?v=2
  2. cm.setValue(md 全文)
  3. 逐张走 paste 上传：python3 tmp/lfl-promo/jj_paste_img.py <本地png> <文件名> 生成 js，再 cdp_eval.py "juejin.cn/editor" tmp/lfl-promo/jj_paste_img.js，每张之间 sleep 2
  4. 上传后正文会出现 ![文件名](https://p0-xtjj...) 行且顺序倒置 → 用 mp_jj_fix.js 删除所有图片行后按章节标题锚点重新插入
  5. 分类点"人工智能"；标签框是 .byte-select__input（非 input），需逐字符派发 beforeinput+input 再点 .byte-select-option
  6. 点"发布"→"确定并发布"
  已发布草稿不能改图片，只能新建草稿重来并删除坏图草稿（POST /content_api/v1/article/delete {article_id} 返回 err_no:0）。
  
  当前性验证（动手前先跑）：ls tmp/lfl-promo/jj_paste_img.py tmp/lfl-promo/cdp_eval.py 确认两个脚本仍存在；再 cd <仓库> && python3 tmp/lfl-promo/cdp_eval.py "juejin.cn/editor" 能返回 ok:true 说明 CDP 9229 仍在。若脚本缺失则本链路不适用，需改用编辑器工具栏上传。
  复现校验：发布后打开 https://juejin.cn/post/<id> 用 read_image 或 cdp_eval 查 img src 应以 https://p0-xtjj 开头且 naturalWidth>600，若 src 含 /imgs/ 说明未上传成功。
evidence: "evidence://v1/1e4b928103d54b9249fd611d0bf6f7bcefc8398c1985591e563d00bf39d7c24f（线上 6 图均为 p0-xtjj CDN、尺寸正常）；坏图草稿 7696343485906370579 已删除 err_no:0"
tags: [掘金, 图片上传, CDP, 发布链路]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-15T00:41:40.869769+08:00"
updated_at: "2026-10-15T00:41:40.869769+08:00"
supersedes: [EXPERIENCE-20261014-知乎-draft-js-掘金-cm5-头条-syl-editor-三平台自动化发布链路与坑-2026]
---