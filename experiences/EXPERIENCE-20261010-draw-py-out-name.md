---
title: 只清理异常文件不修根因则复发：draw.py 路径拼接 OUT+name 缺分隔符
scenario: 处理上一轮遗留的产物/脚本异常时；另注：save_experience 的标题须含至少一个 ASCII token，否则 slug 退化为 untitled 并与同日记录冲突。
root_cause: ""
solution: |
  发现异常文件时，必须区分「现象」与「根因」：只删异常文件而不改产生它的代码，下一轮会原样复发。本轮实证：docs/promotion/figures/_draw.py 的 save() 写成 `p = OUT + name`，而 OUT 无尾部分隔符，产物实际落到 `imgfigN-*.png` 而非 `img/` 目录；上一轮只清理了残留文件并汇报「仓库已清理干净」，根因未动，本轮运行绘图脚本立刻再次生成 5 个错误命名的文件。正确处置：先 grep 出产生该文件名的代码路径，改成 os.path.join(OUT, name) 并补 makedirs，重跑后确认目录内文件数正确、无残留，且 print 输出的绝对路径可直接目视核对落点。
  当前性验证：重跑任一 figures/_g*.py 或 _d2.py 绘图脚本，检查 print 出的绝对路径确实位于 img/ 目录内。
evidence: 上一轮结束时 docs/promotion/ 仍残留 imgfig1-loop.png 且未被识别为问题；本轮运行 _d2.py 后再次生成 imgfig6~imgfig10 五个同名错误文件，且 print 显示 saved 而文件不在 img/ 目录。
tags: [根因, 清理, 绘图, 复现, 代码质量]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-10T18:11:34.405502+08:00"
updated_at: "2026-10-10T18:11:34.405502+08:00"
---