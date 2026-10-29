---
title: 批量修订落盘后必须独立 grep 新旧串复核——&& 链尾命令在替换脚本 assert 失败后仍执行，echo 完成标记会造成假象
scenario: 批量文本修订（审稿必修项落盘）用多命令 && 链执行，替换脚本 assert 失败但链尾命令仍执行，echo 完成标记误导判定
root_cause: ""
solution: 批量替换脚本：assert 全部前置于写盘前；写盘后立即用独立 grep 命令复核新串≥1/旧串=0；完成信号只认 grep 结果不认链尾 echo；关键修订与不相关落盘命令拆链执行
evidence: "docs/promotion/receipts/daily48-toutiao-local.json（执行时间线）；本次修订首次运行回执（stderr AssertionError line 25 + 输出含 LEDGER-OK，退出码 0）；后续独立 grep 发现 md 旧串 6 处残留、台账 3 行追加未落盘；重跑修订后新串 md:3/旧串 0 收口。"
tags: [修订复核, grep新旧串, 完成假象, execute_command链, 推广日更]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-28T20:53:39.629420+08:00"
updated_at: "2026-10-28T20:53:39.629420+08:00"
---

场景：长任务里对稿件/配置做批量文本修订，用一条 execute_command && 链完成「python 替换脚本 + 后续命令（追加/构建/echo 完成标记）」。失败形态：替换脚本内 assert 失败抛异常 → write_text 未执行（文件未改），但 && 链尾的追加/echo 命令仍执行并打印完成标记（fail_fast 沙箱包裹下断链行为与裸 bash -e 预期不符），造成「修订已完成」假象；若不立即复核会拖到下游构建后才暴露。规则：(1) 批量替换脚本把全部 assert 前置到写盘前单独一步（先全量检查匹配串存在再 replace+write），并在脚本末尾回显替换计数；(2) 修订落盘后立即用独立命令 grep 复核「新串≥1/旧串=0」，完成信号只认 grep 结果；(3) 不把链尾 echo/追加命令的输出当完成证据；(4) 关键落盘修订与不相关的追加命令不放同一条 && 链。同族在库：EXPERIENCE-20261026（.replace 静默失效）——本卡增量是「链尾完成标记假象 + 独立 grep 复核」。