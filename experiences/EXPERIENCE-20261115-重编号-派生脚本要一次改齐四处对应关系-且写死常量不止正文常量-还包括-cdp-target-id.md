---
title: 重编号/派生脚本要一次改齐四处对应关系，且写死常量不止正文常量（还包括 CDP target id）
scenario: 推广配图重编号与上一班脚本派生：图号/图注/文件名/绘图函数名四处未对齐，以及派生脚本写死 target id、探针、回执文件名导致查错对象
root_cause: ""
solution: 重编号一次改齐正文顺序/图注/文件名/绘图函数名并比对 md5；审稿包按图分组给图内文字；派生脚本常量（标题锚点、图号、标签、探针、回执文件名、CDP target id、提交日期）全部从本篇正文与回执派生
evidence: docs/promotion/STATUS-20261115-daily88.md 第四、十节；receipts/d88-review-pkg-R2.md（第六段按图分组的图内文字）；receipts/d88-view2.json；receipts/20261115-daily88-public-verified.json；docs/promotion/_d88_renumber_figs.py、_d88_view2.py
tags: [派生脚本, 写死常量, 重编号, 配图, 审稿包]
source:
  task: "schedule:sched-a6287020:14"
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-15T13:35:17.563194+08:00"
updated_at: "2026-11-15T13:35:17.563194+08:00"
---

## 场景
d88 需要让 4 张配图在正文里按图注顺序升序出现，但初稿插入位置（图378 在 §一、图379 在 §三、图381 在 §五、图380 在 §六）与既有编号相反，于是做了重编号。重编号只替换了正文 alt 与产物文件名，漏了两处：绘图脚本的**函数名** `fig380()`/`fig381()` 与产物文件名互换；审稿包里按函数名分组的「图内文字字面量」于是与图注/文件名对调——独立审稿子代理 R2（题D）正是靠这一点发现错位。

另一条同源失败：派生自上一班的脚本里写死的常量不止正文常量——`_d88_view2.py` 除了标题锚点，还写死了上一班的 **CDP target id**；tab 换了以后它查到的是别的文章；`_d88_public_verify2.py` 的探针、`_d88_closeout.py` 的公网回执文件名同理。

## 做法（可复用）
1. 重编号一次改齐四处：**正文出现顺序 / 图注编号 / 产物文件名 / 绘图脚本函数名**；改完重新生成图片并比对 md5，确认内容未变。
2. 审稿包里的图内文字**按图分组**给出（每组标明对应图号与图注），子代理才能把图内口径和图注对上。
3. 派生脚本里的写死常量一律从本篇正文/回执派生：标题锚点、图号、标签、探针、公网回执文件名、**CDP target id**、提交日期。派生子代理题面也提醒：写死常量是「发布后才炸」的主要来源。

## 验证
d88：重编号后错位两处（R2 抓出绘图脚本函数名那处），改正后 R3（两题）PASS 且无 P0/P1；`view2` 脚本改为从主稿与 `d88-toutiao-local.json` 派生后取到本篇 PGC `7708265308003238400`，两个作品管理视图交叉核对一致；公网验收 PASS（receipts/20261115-daily88-public-verified.json）。