---
title: review_admission 发表闸门 0.9 行匹配税：图片行结构性失配 + 编辑器把「刚才」等相对时间词渲染成 rel-time 拆断整行——start 前先自查行配比与时间词
scenario: 向头条等富编辑器发布图文，走 review_admission article_publish 闸门，manuscript 为含 N 张内嵌图片与日常中文口语的 markdown 长文。行数在 45-50 量级、图片 4 张时，0.9 阈值只剩约 2 行容错。
root_cause: ""
solution: start 前自查三步：(1) 数 comparable 行（≥8 字符非空行）与图片行数，图片行占比若使 (行数-图数)/行数 低于 0.95，先增拆正文段落行数摊薄；(2) 全文检索相对时间词（刚才/刚刚/今天/昨天），改写为不受 rel-time 实体化的等义表述（「那条」/「当时」/具体日期）或直接删去——语义无损且保行完整；(3) 首次被拒不改稿义，先看回执 unmatched_sample 判断失配是结构税还是渲染拆断，只修真实拆断行。
evidence: "本会话 review_admission 两次回执：首拒 manuscript_page_text_mismatch match_ratio=0.8936（unmatched_sample 含 4 个 md 图片行与「刚才」拆断行）；修订后同会话 PASS candidate_sha256=fa8664ce…；源码 src/llm_loop/tools/review_host_admission.py:1036-1100 实读；页面侧 page_extra_prose_sample 显示「刚才」处渲染为 <rel-time> 实体。"
tags: [review_admission, article_publish, match_ratio, rel-time, 图文发布, 教训]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-24T20:44:43.260766+08:00"
updated_at: "2026-10-24T20:44:43.260766+08:00"
---

review_admission(kind=article_publish) 的 manuscript_page_text_mismatch 检查实现在 src/llm_loop/tools/review_host_admission.py 的 _manuscript_consistency（实测读源码 1036-1100 行）：对 manuscript 取 _comparable_lines（≥8 字符的散文行，剥 markdown 标记但不剥 ![alt](path) 结构），逐行做「整行是否为页面扁平文本子串」的硬前向匹配，阈值 _MANUSCRIPT_MATCH_RATIO=0.9。两个结构性税：(1) md 图片行 ![图N｜图注…](img/….png) 在页面只呈现为图注文字，带 ![ 前缀与 ](路径) 后缀的整行必不匹配——每图一行固定税；(2) 编辑器会把正文中的相对时间词（实测「刚才」二字）渲染成 <rel-time> 实体，页面文本中该词消失，导致所在整行断开失配。20261024 d36 实发：47 comparable 行中 4 图行 + 1 个「刚才」行失配 = 42/47 = 0.8936 被拒；删除「刚才」二字（语义无损）后 43/47 = 0.9149 通过（receipts/daily36-admission.json note 记录）。d35 为 43/47 险过未暴露。