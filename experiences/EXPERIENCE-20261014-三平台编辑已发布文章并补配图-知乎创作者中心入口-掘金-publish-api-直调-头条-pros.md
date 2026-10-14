---
title: 三平台编辑已发布文章并补配图：知乎创作者中心入口/掘金 publish API 直调/头条 ProseMirror Range+paste
scenario: "用户要求给已发布 12 小时内的科普文（20261013-prefix-cache）在三平台补配 2 张 matplotlib 生成的示意图；上轮已验证\"发布时插图\"，但\"编辑已发布文章\"链路未验证，且旧经验卡断言知乎无编辑入口。"
root_cause: ""
solution: 三平台已发布文章插图的完整可复现链路（每平台一个关键入口+一个坑的解法），全部实跑验证。
evidence: "三平台公网回读：知乎图1 pic4.zhimg.com/v2-7ed80a40 紧跟 H2\"算过一遍的，存起来\"、图2 v2-3af43844 紧跟 H2\"能省多少钱\"；头条图1 p3-sign.toutiaoimg.com/50e9bf714(795px)+图2 89b2a16ee9(lazy data-src)；掘金文章页 DOM 2 图 p6-xtjj-sign.byteimg.com(795px/1000px) 分属正确 H2。receipts: docs/promotion/receipts/20261013-prefix-cache-{zhihu,toutiao,juejin}.json 已更新 history。"
tags: [multi-platform, editor, image-upload, zhihu, toutiao, juejin, cdp, api-publish]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T00:56:50.718165+08:00"
updated_at: "2026-10-14T00:56:50.718165+08:00"
---

## 关键路径
1. **知乎**：创作者中心 www.zhihu.com/creator/manage/creation → 目标文章卡片"编辑"链接(A标签, href=/p/{id}/edit) → 编辑器打开已发布文章（/edit 不再重定向，2026-10-10 旧结论已失效）。编辑器为 Draft.js：光标定位到 H2 末尾(点击行右侧+End)→ 合成 ClipboardEvent("paste") 带 File(image/png) dispatch 到 [contenteditable=true] → 图落 selection 位置。删除图块：点击图片(选中态)+Backspace。保存=右下"更新"按钮。**坑：编辑器声明字段回填丢失，默认"无声明"，更新前必须在发布设置里重选"包含 AI 辅助创作"**（在左栏 popover，click 触发展开，选项 x≈360 列）。公网验收:登录态 fetch 文章+DOMParser，ContentItem-time 应显示"编辑于 xx ・包含 AI 辅助创作"。
2. **头条**：mp.toutiao.com/profile_v4/graphic/articles 行"修改"(操作列与标题列分离布局,按钮在行中垂直位置≈标题y+98) → from=edit 编辑页(ProseMirror)。插图最稳法：JS document.createRange()+selectNodeContents(h1)+collapse(false)+window.getSelection().addRange(range) 精确设光标 → paste ClipboardEvent 带 File dispatch 到 .ProseMirror → 图落位（直接坐标点击 H1 末尾不可靠，会插到文首）。删图：点击图块容器(rect 取 fig 而非 img,lazy 图 img 宽为0)+Backspace。保存=顶部"发布"→ 列表显示"审核中"，公网图渐进生效（图2 可能 lazy data-src 存在）。
3. **掘金**：编辑入口在创作者中心 /creator/content/article/essays 行"···"下拉（hover 打开，合成 click 会 fade-leave 抓不到）——**绕开 UI**：api.juejin.cn/content_api/v1/article/list_by_user POST {user_id,sort_type:2,cursor:"0"} 拿 article_info.draft_id → 直开 juejin.cn/editor/drafts/{draft_id}（CodeMirror markdown 编辑器）→ cm.setCursor 到 H2 行 + paste ClipboardEvent dispatch 到 cm.getInputField() → 图上传自动插入 markdown。**发布坑：面板"确定并更新"按钮 CDP 点击/坐标点击/el.click() 全部吞事件零网络请求（原因未明），解法=直调 api.juejin.cn/content_api/v1/article/publish POST，body 取 draft detail 的 category_id/tag_ids(必须字符串数组)/brief_content，draft 已绑定 article_id 时返回同 ID=更新成功**，私域图 URL 发布后自动转 p6-xtjj-sign.byteimg.com 签名 CDN。

## 通用
- CDP websocket 必须 suppress_origin=True（否则 403）
- 头条 tab 内 fetch 主站被安全 SDK 拦（"暂不支持"），公网验收去文章页 tab 刷新后查 DOM
- matplotlib 需 /tmp/mplvenv（系统 python3 是 PEP668 externally-managed）；CDP 脚本用 /opt/homebrew/bin/python3（有 websocket-client）；工作区 .venv 无 pip 是空壳