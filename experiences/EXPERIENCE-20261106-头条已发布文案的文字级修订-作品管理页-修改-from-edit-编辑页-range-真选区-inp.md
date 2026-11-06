---
title: 头条已发布文案的文字级修订：作品管理页「修改」→ from=edit 编辑页 → Range 真选区 + Input.insertText 替换 → 发布后转「修改审核中」再转已发布
scenario: "今日头条图文已发布（作品管理页显示「已发布」）后，发现正文里若干处文字级缺陷（数字口径错、行号错、措辞夸大）需要修正。头条没有知乎那种 /p/{id}/edit 路由，编辑入口在作品管理页的「修改」。"
root_cause: ""
solution: "入口：作品管理页（mp.toutiao.com/profile_v4/graphic/articles）找到本篇卡片的「修改」span，点击后平台会新开一个标签页到 https://mp.toutiao.com/profile_v4/graphic/publish?from=edit&pgc_id=<PGC_ID>（务必用这个新标签页，别在旧标签上操作）。补丁手法与知乎 Draft.js 同构但编辑器不同：ProseMirror 里用 TreeWalker 找含目标串的文本节点 → document.createRange() 建立真实选区 → window.getSelection().addRange() → 元素 focus() → 发 CDP Input.insertText（带 text 参数）替换。多处替换要逐处做，选区会被上一次替换清掉。提交前自检：正文非空白字数、图片 DOM 数（平台每图两个节点，图数=DOM/2）、图注块数与顺序、h1 数与空 h1 数、标签数、AI 声明勾选态。点「发布」后页面直接跳回作品管理页（编辑页没有「确认发布」浮层），卡片状态会先变「修改审核中」再转「已发布」，两个态都要轮询见到。按 RULE-AI-28，编辑页点「发布」之前同样要 review_admission(action=start, kind=article_publish) 取到 PASS——宿主要求目标页上真的看到发布按钮，否则报 publication_button_not_observed；此时绑定页必须是编辑页而不是作品管理页，用 browser_perceive(snapshot, target_id=<编辑页 page_id>) 换绑。补丁后复核：新串在编辑页与公网页各 ≥1、旧串各 =0。"
evidence: "2026-11-06 午班 d65：头条 PGC 7704927716709007906。作品管理页点「修改」→ 新标签 publish?from=edit&pgc_id=7704927716709007906 → ProseMirror 内 TreeWalker+Range 真选区+CDP Input.insertText 替换 6 处文件行数（641→wc -l 共 640 行 等），编辑页复核新串 6 条各 1、旧串 6 条各 0；二次 review_admission（child subagent_37a049f382b2，candidate 3a97fcc7247791b3…，PASS，宿主固定 GLM-5.3）后点「发布」→ 13:59:21 卡片「修改审核中」→ 13:59:50 转「已发布」；公网复验新串 6 条全命中、旧串零命中、5 图尺寸逐一相等、5 图注命中、文章区 3 标签在位。回执：docs/promotion/receipts/daily65-admission-revision.json、20261106-daily65-public-verified-revision.json、d65-poll-revision.log。"
tags: [promotion, 今日头条, 编辑页, Input.insertText, 发布后修订, review_admission]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-06T14:03:39.565441+08:00"
updated_at: "2026-11-06T14:03:39.565441+08:00"
supersedes: [EXPERIENCE-20261025-公众号图文-type-10-才是图文编辑器-prosemirror-正文可无损-paste-封面自动]
---