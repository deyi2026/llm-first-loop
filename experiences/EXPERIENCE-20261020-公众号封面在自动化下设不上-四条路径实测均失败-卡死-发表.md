---
title: 公众号封面在自动化下设不上：四条路径实测均失败，卡死「发表」
scenario: 微信公众号图文编辑器（mp.weixin.qq.com）给一篇已写好的长文设置封面，作为点「发表」的前置步骤
root_cause: ""
solution: 封面无法通过浏览器自动化设置，四条路径全部实测失败，须由真人在页面手动选一次。判据与坑：①正文图被包在 section 里，「从正文选择」列表为空；②图库选中后确定按钮根本不渲染（用 getClientRects 而非 offsetParent 判可见）；③AI 一键生成封面的「使用」按钮点击无效；④拖拽可打开 jCrop 弹窗但「确认」无响应。未设封面时「发表」必被弹回封面弹窗，且按钮 disabled 属性为 false，不能据此判断可否发表。
evidence: docs/promotion/STATUS-20261020-why-agent-now-zhihu-wechat.md「未闭合 1/2/3」；/tmp/wx_cov*.py 四条路径的逐步回执（选项坐标、file input nodeId、selected 态、jcrop 弹窗、确认无响应）
tags: [公众号, 封面, mp.weixin.qq.com, 阻塞, 浏览器自动化]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-20T22:09:00.485868+08:00"
updated_at: "2026-10-20T22:09:00.485868+08:00"
---

2026-10-20 在 mp.weixin.qq.com 为一篇长文设封面，四条路径全部失败：
1) 「从正文选择」：列表为空——正文图是 paste 上传后被包在 `<section data-card>` 里的，平台不识别为可选封面（列表提示"请从正文插入的图片和视频封面中选择封面"，0 项）。
2) 「从图片库选择」：file input 可用（DOM.setFileInputFiles 能把图传进素材库，库计数 2→3），选中后 item 出现 selected 态与勾选框，但弹窗页脚只渲染出「取消」，「确定」始终 0 尺寸（getClientRects 为空）——注意不能用 offsetParent 判断可见性，position:fixed 元素 offsetParent 恒为 null，要用 getClientRects().length。
3) 「一键生成封面」：候选图正常生成（「使用」按钮 class=.ai-image-op-btn），坐标点击与 JS click 均无响应。
4) 向 .js_cover_btn_area 派发 dragenter/dragover/drop（DataTransfer 带 File）：确实打开了 jCrop 编辑封面弹窗且图片已上传 mmbiz，但「确认」按钮（真实鼠标事件）以及先拖拽裁剪框再确认都不关闭弹窗。
连带事实：未设封面时点「发表」会被直接弹回封面弹窗，DOM 上按钮 disabled 属性为 false（不能靠 disabled 判断）。此外该账号未实名认证，发表/群发能力受限，且草稿箱列表（action=list_card&sub=list&type=10）读不到本篇，只有编辑器内「已保存」字样——按"发布类任务必须核验线上终态 URL"不能据此宣称已发布。
结论：设封面需要真人手动点一次；不要在此之前反复重试自动化。