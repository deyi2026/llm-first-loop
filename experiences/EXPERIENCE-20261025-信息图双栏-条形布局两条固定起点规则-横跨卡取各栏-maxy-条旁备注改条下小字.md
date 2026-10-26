---
title: 信息图双栏/条形布局两条固定起点规则：横跨卡取各栏 maxY、条旁备注改条下小字
scenario: LFL 每日推广稿的信息图绘制：1000px 宽画布，左侧纵向阶梯/条形多行 + 右侧短栏 + 底部横跨说明卡的复合布局；或条形图带文字备注
root_cause: ""
solution: "横卡起点=max(各栏 maxY)+间距；条旁备注改条下小字行；写码时先逐栏累计 Y 再定横卡位置，生成后 bottom_check+read_image 复验。当前性验证：grep -n '244 + 8 \\* 50 + 34' 与 'y + 48), note' docs/promotion/figures/_d39.py 两处均在"
evidence: "~/lfl-workspace/docs/promotion/figures/_d39.py（fig166/fig168 两段修订 diff）；read_image 首轮发现遮挡与截断、修订后复验 PASS（2026-10-25 20:16-20:29）"
tags: [promotion, 信息图, PIL, 布局]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-25T21:06:36.443742+08:00"
updated_at: "2026-10-25T21:06:36.443742+08:00"
---

PIL 信息图（_draw.py 系）双栏/条形布局两次返工的合并教训：①fig166：说明卡起点 y=610 只看了右栏（6 行）高度，左栏 9 行阶梯实际延伸到 y≈746，横卡直接盖住左栏 P5+/P6/P7 三行（read_image 首轮发现）。规则：**任何横跨多栏的下方卡片，起点必须取 max(所有栏实际底 Y)+间距**，逐栏算 maxY 再取 max，不能只看短栏。②fig168：条形图备注文字放条形右端（x1+90 起），22/60 的条已到 x=828，备注溢出 1000px 画布右缘被裁。规则：**条旁备注改为条形下方小字行（y+48，行距相应加到 76）**，数值仍可贴条右端。两处修复后 bottom_check+read_image 复验通过。当前性验证：grep -n 'max(maxy, 244 + 8 \* 50 + 34)' docs/promotion/figures/_d39.py 应命中 fig166 段取各栏 maxY 的写法；grep -n 'd.text((52, y + 48), note' 同文件应命中 fig168 条下备注行。