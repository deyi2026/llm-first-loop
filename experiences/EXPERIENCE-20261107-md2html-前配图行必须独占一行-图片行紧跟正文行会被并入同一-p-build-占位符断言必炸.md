---
title: md2html 前配图行必须独占一行：图片行紧跟正文行会被并入同一 <p>，build 占位符断言必炸
scenario: "LFL 推广班次写稿后跑 md2html.py + 发布 HTML 构建脚本（把 ![]() 占位成 %%IMGn%% 再替换成 data-URI 内嵌图），d69 晚班 2026-11-07：构建脚本在第 2 张配图处直接 AssertionError: placeholder 1 missing，第 1 张却能通过。"
root_cause: md2html 的段落分支会把「不匹配任何块级语法的连续非空行」合并进同一个 <p>。当某条配图行紧跟在一个正文行后面（中间没有空行）时，图片行被并入正文段落，占位符不再是独立的 <p>%%IMGn%%</p>，构建脚本的占位符断言随即失败；而紧跟在列表项后面的配图行因为列表分支先消费掉了列表项，反而正常——所以错误只出现在部分图上，表现为「第一张过、第二张炸」，很容易误判为随机故障。
solution: "写稿阶段就保证每条配图行前后各留一个空行；若已写坏，build 前用一个脚本统一在配图行前后插空行。转换后机械断言：md 图片数 == HTML img 数、残留标记（%%IMG/![/<p>fig）计数为 0、配图 alt 段数 == 图片数。当前性验证：跑 `python3 docs/promotion/_d69_build.py` 应得 BUILD PASS 且输出里 md_imgs == html_img、resid == 0；或跑 `grep -n -B1 '^!\[图' docs/promotion/20261107-lfl-daily-69.md` 检查每条配图行前一行是否为空行（若前一行是正文行则该图会被并入段落）。"
evidence: "本班真实失败：docs/promotion/_d69_build.py 抛 AssertionError: placeholder 1 missing；定位后新增 docs/promotion/_d69_fix_imglines.py 统一插空行，重跑 BUILD PASS（md_imgs 5 == html_img 5、resid 0、h1 12、empty_h1 0）。回执 receipts/d69-build.json。"
tags: [promotion, md2html, toutiao, build, pitfall]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-07T20:32:42.642475+08:00"
updated_at: "2026-11-07T20:32:42.642475+08:00"
---