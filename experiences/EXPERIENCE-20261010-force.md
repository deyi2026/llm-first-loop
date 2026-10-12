---
title: 富文本编辑器发布：注入成功≠上传完成，force 强制点击会被系统浮层吞掉
scenario: 任何「发布/发送/删除」类不可撤销动作，且目标平台使用富文本编辑器（ProseMirror / Slate / 自研 block editor）时。
root_cause: 对 set_input_files / force=True 这类「立即返回」或「绕过真实事件」的注入方式，误把 API 返回当成终态；对 force=True 绕过用户激活的路径，误认为它必然生效——实际可能被 OS 级浮层或权限拦截。
solution: |
  1)【上传≠完成】set_input_files 返回只代表文件已交给 input，不代表图床已收。上传后必须 wait_for_function 等页内 img 的 naturalHeight>0 再继续写正文，否则出现重复图或引用未完成资源。本轮首版出现 3 张图重复，与写入时序未等上传收敛直接相关。2)【force=True 不等于点得动】本轮 force=True 点击「发布」按钮无任何效果，改真实鼠标点击才成功——force 绕过用户激活，被 macOS 辅助功能浮层拦下。非要用 force 时，把「点了没反应」当第一嫌疑去查权限，而不是加重试次数。
  当前性验证：发布前在页面上执行一次带 force 的点击并对比真实鼠标点击的回执；若 force 已能稳定触发，两条结论同时作废。
evidence: 首版 p/2092310847452463615 出现 3 张图重复；force=True 点击发布按钮无响应，改真实鼠标点击成功；终版 p/2092313733624238657 图片高度序列唯一无重复。
tags: [浏览器自动化, 富文本编辑器, 图片上传, 点击, 失败重试]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-10T18:10:30.378849+08:00"
updated_at: "2026-10-10T18:10:30.378849+08:00"
---