---
title: 头条发布 confirm 后列表缓存延迟：未见新稿先强刷再判失败，防重复提交
scenario: 头条 mp.toutiao.com 作品管理列表（profile_v4/graphic/articles）在 CDP confirm 发布后存在约数十秒的列表缓存延迟：confirm 已成功（AFTER_URL 跳转到列表页、无错误弹窗），但立即查询列表时新稿不出现、总计数不变，易误判「提交失败」而触发重发（重复提交同稿）。本场景发生于 LFL 每日推广的头条发布链路。
root_cause: ""
solution: confirm 返回 AFTER_URL=articles（成功跳转信号）后，若列表首次查询未见新稿：不要立即断言失败或重发，先对该 tab 执行 Page.reload(ignoreCache) 再等 5-7 秒复查计数与首条标题；仍未见才进入失败排查（检查弹窗/toast/草稿箱）。发布成功的权威信号优先级：confirm 脚本回执 > 强制刷新后的列表实见 > 首次列表查询。
evidence: "receipts/daily34-toutiao-local.json（confirm 阶段 after_url=profile_v4/graphic/articles）；两次列表查询输出对比（08:2x 共49条/无77%标题 → reload 后 共50条/首条77%标题·审核中·10-24 08:25）"
tags: [toutiao, publish, cdp, cache-delay, verify]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-24T08:27:13.245287+08:00"
updated_at: "2026-10-24T08:27:13.245287+08:00"
supersedes: [EXPERIENCE-20261018-头条发布成功与否不能以即时列表为准-列表未出现-发布失败-须轮询-公网回读双确认]
---

2026-10-24 早班 d34 发布：_d34c_full.py confirm 回执 AFTER_URL=articles 且无弹窗，8 秒后查询作品管理列表「共 49 条」且搜不到新稿标题，险些误判为提交失败准备重发。强制 Page.reload(ignoreCache) 后 7 秒实测：计数 49→50、首条即新稿（审核中）。时间戳 10-24 08:25 与 confirm 时刻吻合，证明提交早已成功，此前是列表数据缓存延迟。反面风险：若据单次未见就重发，会造成同稿重复提交（任务硬门明令禁止）。判据：confirm 链路的权威信号是 AFTER_URL 跳转+提交回执，列表只是展示层；列表未见新稿时先 reload 再断言。相关：d34 发布会话 sched-0300b296:5。