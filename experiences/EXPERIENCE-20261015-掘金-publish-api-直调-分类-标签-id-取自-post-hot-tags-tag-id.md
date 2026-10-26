---
title: 掘金 publish API 直调：分类/标签 ID 取自 POST hot_tags，tag_ids 必填，账号限制返回 err_no 1012
scenario: 掘金（juejin.cn）发布面板「确定并发布」按钮吞事件（本次 element.click() 与真实 CDP mouseMoved/Pressed/Released 复现，performance 里零 article/publish 请求），改走 content_api/v1/article/publish 直调。
root_cause: 面板按钮的提交链路在自动化下不触发（既有经验卡已记录，本次再次复现）。另有两个此前未记录的硬约束：tag_ids 为空时服务端直接拒发（err_msg「至少添加一个标签」），且最终被账号级限制拦截（err_no 1012）。
solution: |
  补充既有 publish API 经验卡未覆盖的取 ID 路径：query_category_list / query_tag_list 必须用 **POST**（GET 一律 err_no 2），且嵌套层是 list[i].category.category_id / .category_name、list[i].tag.tag_id / .tag_name——直接取 category_id 会得到 undefined。与分类同名标签被禁用（既有卡已记）。真正可用的 AI 类标签不在 query_tag_list（那里全是前端/后端框架标签），而在**分类对象的 hot_tags 数组**里，本次取到：人工智能=6809637773935378440、LLM=7257794499869573175、Agent=7516396389476401162。
  
  新增硬约束：tag_ids 不能为空数组，否则服务端拒绝；分类同名标签不可用，故选 LLM + Agent 而非 人工智能。
  
  标签输入框 .byte-select__input 不接受任何合成输入：逐字符派发 beforeinput+input、Input.insertText、Input.dispatchKeyEvent 三种方式实测均无字符进入，选项列表也不过滤（是静态推荐列表）。因此**不要在 UI 上找标签**，直接用 hot_tags 的 tag_id 调 API。
  
  终止纪律：返回 err_no 1012「账户目前受到限制，暂时无法发布文章」属平台侧账号门控，只尝试 1 次即停，不重试刷发布（可能加深限制），草稿已完整保存（正文 78/78 行、6 图全部落 CDN、分类标签已设），解除限制后可直接发布无需重建。
evidence: "publish API 直调实测：err_no 1012 / err_msg「抱歉，您的账户目前受到限制，暂时无法发布文章。」；此前一次 tag_ids=[] 返回「至少添加一个标签」。UI 吞事件由 performance.getEntriesByType('resource') 过滤 article/publish|draft/update 确认：真实鼠标事件后仍无 publish 条目。草稿 draft_id=7696702096704700457 无损对照 78 行 0 缺失/图 6 唯一有序 exit=0。回执 docs/promotion/receipts/20261015-lfl-memory-juejin.json。"
tags: [掘金, publish-api, category_id, tag_ids, 账号限制, CDP]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-15T17:07:29.124491+08:00"
updated_at: "2026-10-15T17:07:29.124491+08:00"
---