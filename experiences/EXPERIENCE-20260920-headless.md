---
title: 浏览器诊断先清点实例再下登录态结论：绑定页可能落在遗留 headless 实例
scenario: "浏览器自动化/诊断任务中，本机可能同时存在用户日常 Chrome（无调试口）、headed 调试实例、多个遗留 headless 实例（测试/eval 残留，动态端口）；需通过 runtime 浏览器工具或 CDP 观察页面并下\"登录态/页面状态\"结论时。"
root_cause: 多 Chrome 实例并存时，把 headless 遗留实例（45918）的登录页当成用户浏览器的 Gmail 登录态，未做实例/端口清点就下结论。
solution: "下\"登录态/页面状态\"类结论前强制执行实例清点三件套（ps 主进程、lsof LISTEN 端口、逐端口 /json/list 核对 target URL 与 title），先确认绑定页属于哪个实例、与用户所指窗口是否同一 target，再下结论；发现遗留 headless 实例先报告用户并建议清理，不基于其实例状态推断用户会话。"
evidence: "lsof LISTEN：9222/45918/62427 三个端点；45918 /json/list 唯一 page=accounts.google.com/v3/signin/identifier?continue=mail.google.com（version UA=HeadlessChrome/153，ps 98741 Fri04PM --user-data-dir=…/browser_mount_test/chrome-profile）；62427 唯一 page=Browser A/B Fixture（排除）；9222 target E4A42A0CB3CC26D5B4C8E0AB09560AD7=mail.google.com/mail/u/0/#inbox \"Inbox (83) - dysy1090@gmail.com\"（排除登录页所在）；绑定页快照 bsnap-71 内容=Google 登录页，与 45918 唯一页面 URL 吻合。证据：evidence://v1/8fa33426e6390eafd5c811c6d22f9b917fac29d2a6e47117b62784ee353c4ef5、evidence://v1/04b080f6b2ec3e0e5cb4eed4c81bae0db4888cc650cceae39544d3f94285f1bc"
tags: [browser, cdp, 诊断流程, 后台浏览器, 登录态误判]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-20T13:50:53.415624+08:00"
updated_at: "2026-09-20T13:50:53.415624+08:00"
---

2026-09-20 Gmail 任务中，连续两轮向用户误报"Gmail 登录态已失效/弹回登录页"，而用户屏幕上 Gmail 明明是登录的。根因：本机同时存在 3 个 CDP 端点（lsof 实证）：9222=13:25 拉起的 headed 调试 Chrome（~/chrome-debug profile，Gmail 已登录 Inbox (83)）；45918=上周五 browser_mount_test 的 nohup 脚本拉起的 --headless=new Chrome（空 profile，唯一页面是 accounts.google.com/v3/signin/identifier?continue=https://mail.google.com/mail/u/0/）；62427=周三 eval 遗留 headless（只挂 127.0.0.1:62426 Browser A/B Fixture）。runtime browser_perceive/browser_operate 绑定的页面落在 45918 headless 实例——从未登录过 Google，导航 Gmail 必弹登录页。教训：(1) 报告任何"会话/登录态"结论前，必须先做实例清点三件套：ps 全量 Chrome 主进程、lsof -iTCP LISTEN、逐端口 curl /json/list 核对 target URL/title，确认"我看的页面"与"用户所指页面"是同一 target；(2) runtime 绑定页 ≠ 用户可见窗口，多 CDP 端口并存时绑定可能落在遗留/测试实例上；(3) 用户质疑"是不是在用后台浏览器"时立即核实实例清单再回答，不辩解工具语义。