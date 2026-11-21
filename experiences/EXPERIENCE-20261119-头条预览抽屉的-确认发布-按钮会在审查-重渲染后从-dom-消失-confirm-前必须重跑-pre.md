---
title: 头条预览抽屉的「确认发布」按钮会在审查/重渲染后从 DOM 消失，confirm 前必须重跑 preview
scenario: "LFL 推广发表流程：宿主 review_admission 审查期间，页面被重渲染，抽屉里的「确认发布」按钮从 DOM 消失（实查 confirm_leaves=[]、text_mentions=false）。此时 publish.py confirm 报 NO_CONFIRM_BTN。"
root_cause: ""
solution: 在 confirm 之前重跑 publish.py preview（重新点「预览并发布」开抽屉），确认按钮存在且 inView=true，再立刻执行 confirm（两次调用之间不要插长耗时步骤，否则按钮可能再次被移除）。preview_refresh 阶段要逐行比对抽屉副本与编辑器正文（missing_lines 必须为空），排除旧副本误判。当前性验证：跑 publish.py preview 后用 CDP 查 confirm_leaves 长度应 >0 且 inView=true；若仍为空说明抽屉未真正打开，需检查预览按钮是否点击成功。
evidence: "回执 evidence://v1/ea9e279bb99a9c37292fd43a4cf8562e09108d77bec5b8dff976ce977f56b111（preview 后 CONFIRM_BTNS x=862 y=699 inView=true）；evidence://v1/892b3ddf79917ea91f1721fcd8f0dcacbb7f0c3738e1dba61f3e0a9734c756b（confirm 报 NO_CONFIRM_BTN，PRECONFIRM UNCHANGED）；evidence://v1/67f2716182447cfe81a51fded1e150405f4ee4a65cc7f5df1123dc79f8d14b38e（抽屉与编辑器逐行 diff：missing_lines=[]，多出的全是平台 UI 文本）。"
tags: [头条, 发布, preview, confirm]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-19T16:55:45.295060+08:00"
updated_at: "2026-11-19T16:55:45.295060+08:00"
---