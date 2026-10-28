---
method_id: runtime-ui-literal-key-scoped-grep-before-repo-wide-search-5fb187df770d
name: runtime-ui-literal-key-scoped-grep-before-repo-wide-search
description: 前端控件在真实运行中交互零效果（点击后零请求、按钮状态不变）时，找 owner 代码不要从仓库根发起全量搜索（会撞权限拒绝、node_modules 超时）。排查前探针输出里已捕获该控件的确切渲染 label/标题/class token——这几乎是唯一的源码定位键；先用一次 ls 分清第一方源码根（前端 webui/src vs python src/），再在根内 grep 该字面量直达组件，读 handler 找交互前置条件，与探针观察对齐后修正复跑。
aliases: 点了按钮没发请求去哪查代码, 界面文案反查前端组件实现, 控件零请求排障先找 owner 源码, 拿渲染文案当定位键, 大仓库找按钮 handler 先分前端根
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:80f5e2cd-19c2-42bb-8bca-1c0a01cc2a48:5907:b8e46c53ee9692e36337
evidence_refs: learning:learn:3ffbd10e93f7
created_at: 2026-10-28T10:33:00.063430+08:00
updated_at: 2026-10-28T10:33:00.063430+08:00
---
## Trigger
页面/前端控件在真实运行中交互零效果（点击后零网络请求、状态不变），需要定位其处理逻辑源头；或要在含多个第一方源码根（前端根与后端根并存）的大型仓库里找某个 UI 行为的 owner 代码。

## Discriminator
进入源码排查之前，探针 console 已逐字打印控件渲染字面量（button label『开启实时语音（点击开启，连接就绪后按住说话）』+ 页面标题）——这是几乎唯一的 grep 键；且仓库根一次 ls 即可区分前端根（webui/src）与 python src/，无须全仓枚举（全仓 search 会撞敏感目录拒绝、全仓 grep 会 60s 超时）。

## Short path
- 从已捕获的运行时输出（探针 console/Network/DOM 快照）提取控件唯一字面量：label、可见文本、页面标题或 class token
- 一次 ls 列出仓库根，识别第一方前端源码根（自带 package.json/src 的目录），排除 node_modules/dist/vendor
- 在该根内 grep 该字面量，命中 owning 组件（如实时语音按钮 → RealtimeVoiceBar/Composer）
- 读组件 handler，找出点击前置条件/守卫（权限、配置、会话态），与探针观察的『零请求』逐项对齐
- 按前置条件修正探针或环境后复跑基准，验证 Network 捕获出现预期请求且控件状态变化

## Stop conditions
- 已定位 owning 组件并解释零请求的直接原因（守卫/前置条件不满足），且复跑最小探针后请求与预期行为一致
- 字面量 grep 落空且确认文案来自 i18n/后端下发，已切换为 class token/选择器/sourcemap 反查

## Verification
- 复跑最小探针：enable 点击后 Network 捕获出现预期请求、按钮 label 状态翻转
- 组件内每个守卫条件与探针运行环境逐项核对（权限授予、登录会话、配置开关）
- 最终以端到端黄金基准（音频上行→流式转写→LLM 处理）复现全绿收口

## Counterexamples
- 症状在服务端：请求实际已发出且返回 4xx/5xx（如手动 POST 得 422）——应查后端路由/日志，UI 字面量键无效
- 文案来自 i18n 资源或后端下发，源码中不存在该字面量——grep 落空，改用 DOM class token、选择器或 bundle sourcemap 反查
- 小仓库且搜索工具可用且快——一次 scoped search 即可，无须先 ls 分根
- 失败原因是运行时环境策略（权限弹窗、autoplay）而非前端逻辑——应走『读 API owner 源码审计兜底』路径而非本方法
