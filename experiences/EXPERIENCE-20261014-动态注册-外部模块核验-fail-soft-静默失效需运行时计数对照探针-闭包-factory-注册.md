---
title: 动态注册/外部模块核验：fail-soft 静默失效需运行时计数对照探针；闭包 factory 注册需分名绑定+实调测试
scenario: 独立项目经 importlib 动态注册进宿主 engine（fail-soft：未配置静默/失败 warning 不注册），测试全绿但生产形态失效
root_cause: ""
solution: 决定性探针=运行时 registry 计数对照配置源计数差值；进程外用同款加载路径复现（sys.path 注入+接缝调用）二分定位；修复配套「生产形态」回归测试（默认 dotenv 路径布局单测 + factory builder 实调用捕获 settings 断言）
evidence: "evidence://v1/6480e6e9dc20f5c55b5321a89d0be35a518f1f2dc9d0509cb93aa59776ae512a6b（registry 5/28 计数探针）；~/Project/lfl-web-providers 6220dfc/ae87bee 修复提交与回归测试；reports/web-carveout/g4/ROUNDTRIP.json（修复后等价往返 OK-G4）"
tags: [dynamic-registration, fail-soft, dotenv-layout, closure-capture, real-loop-verification, provider-carveout]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T07:35:17.221715+08:00"
updated_at: "2026-10-14T07:35:17.221715+08:00"
---

web-carveout G4 核验时，外部注册模块在生产进程内静默失效：/api/v1/providers 端点 providers 列表只反映磁盘 raw 配置，运行时 registry（含外部 specs）只体现在 effective_provider_count/effective_model_count 字段——只解析列表会误判「端点不含外部条目=正常」，对比计数才发现 raw 5/28 == runtime 5/28（外部注册零生效）。根因1：外部模块 config._package_root() 在 src 布局返回 src/，读不存在的 src/.env（真实 .env 在项目根）→ enabled=False → fail-soft 静默不注册、无 warning——「未配置」与「加载失败」在日志上不可区分。根因2：两通道块复用局部变量名 duck，lambda 闭包按引用捕获，chatgpt 块重绑定后劫持 deepseek factory（双通道同时 enabled 才触发=生产形态）。测试两者都没抓到：dotenv 用 env= 显式注入（未测默认路径生产形态）；factories 只断言键集合未实调 builder。修复+回归：布局候选搜索（上溯2级平铺→3级src布局）+ _find_dotenv 纯函数布局单测；分名绑定 + 假 build 捕获 settings 的双通道实调测试。方法论：动态注册类功能必须有「运行时计数 vs 配置源计数」的差值探针；「成功路径静默」的接缝（只 warning 失败）意味着无日志≠已注册；闭包 factory 注册模式测试必须实际调用。