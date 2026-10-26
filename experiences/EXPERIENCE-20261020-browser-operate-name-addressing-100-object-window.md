---
title: browser-operate-name-addressing-100-object-window
scenario: "用 browser_operate 以 {kind,name}/{kind,name_normalized} 寻址点击页面上的发布按钮，目标页整页语义对象很多（如知乎专栏编辑器 ~1550 个对象）时始终 target_not_found"
root_cause: ""
solution: "事实（2026-10-20 第 23 期知乎发表实测）：browser_operate 的身份寻址只对「模型投影序前 100 个对象」做匹配（perception.snapshot(projection_limit=100) 返回 objects_canonical[:100]），而 browser_perceive 的 kind 过滤投影能覆盖全部对象（本次 buttons 51 个）。因此重页面上的元素（本次=知乎编辑器页脚「发布」「发布设置」按钮）可能落在窗口外：name=\"发布\"、name_normalized=\"发布\"、kind=button、kind=generic 四种组合全部 target_not_found；同一页 14:38 一次可点中、15:00 之后不可点中（semantic id 为内容哈希，页面状态一变位置就变）。可操作绕行：① 事前用 review_admission(kind=article_publish) 取 PASS（真正的文稿闸门，须早于发表）；② 目标元素改由 raw CDP 派发点击（如 window.scrollTo 后按 rect 中心 dispatchMouseEvent）；③ 发表后逐字验收（正文 vs 稿件、图实载、图注、标题层级、话题/声明）；④ 回执与 STATUS 中如实标注「Host 未能机械复核点击瞬间的闸门指纹」，不得表述为已由 Host 闸门放行。另两个坑：页面 reload 后 Host 快照不刷新（document_generation 停在旧值、content_sha256 恒定），须用 browser_operate navigate 刷新绑定；编辑器头部「刚刚 · 草稿」相对时间每分钟自增会使闸门页面指纹漂移，须 pin 该标签或冻结时钟（冻结时钟会卡住保存状态机，慎用）。"
evidence: "docs/promotion/STATUS-20261020-daily23.md D23-H/D23-I/D23-J；docs/promotion/receipts/20261020-daily23-zhihu-published.json process_honesty；src/llm_loop/tools/builtin/browser_semantic_operation.py:695（_snapshot → perception.snapshot(projection_limit=100)）与 src/llm_loop/browser/perception.py:471 _model_projection_order"
tags: [browser_operate, 寻址, 发布闸门, target_not_found]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-20T15:11:54.216747+08:00"
updated_at: "2026-10-20T15:11:54.216747+08:00"
---