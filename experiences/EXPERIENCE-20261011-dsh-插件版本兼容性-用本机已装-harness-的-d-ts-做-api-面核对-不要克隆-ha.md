---
title: dsh 插件版本兼容性：用本机已装 harness 的 .d.ts 做 API 面核对，不要克隆 harness 仓库
scenario: 判断第三方 dsh 插件（如 ds-bot）能否在当前 dsh 版本上跑通；曾打算克隆对应 tag 的 dsh 仓库源码核对。
root_cause: ""
solution: |
  不要克隆 harness 仓库。/Users/yyj/.local/dsh/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/<pkg>/lib/types/**/*.d.ts 就是当前运行版本 0.1.7-rc.2 的权威 API 面，且 types 目录是嵌套的，必须用 `grep -r` 递归到 $D/*/lib/types/ 而不是 glob 顶层 *.d.ts（顶层 glob 会漏掉 uiWorkspace/uiConversation/configForms/slots 等 client 侧服务，误报 NOT FOUND）。
  服务名不在代码里字面出现：cordis Service 以 `static provide` 命名，ClientContext 侧则是 d.ts 里 `uiWorkspace: X` 之类的字段声明，所以核对服务是否存在要 grep d.ts 的 Context 字段声明，不能 grep `ctx.set('...')`。
  核对清单四件套：(1) inject 列表里每个服务名是否在某个 d.ts 的 Context 字段中声明；(2) 每个 ctx.<svc>.<method>() 调用点是否有匹配的 .d.ts 签名（注意 client 侧走 dsh-api-session-controller/lib/types/client/contract/*.d.ts 的 ISessions 代理接口，与 host 侧 SessionStore 不同）；(3) 监听的每个事件名字符串是否在 d.ts 中出现；(4) 实际解析到的各 package 版本号是否一致。
  本次结果：ds-bot 的 8 个 host 服务 + 6 个 client 服务 + 全部调用点 + 7 个事件在 0.1.7-rc.2 上全部存在且签名一致。
evidence: "evidence://v1/1b8141fd4368cbae0a71d1ccf9d37807605cbd0ac9bd0f2c7d1d0dcd15a12d1"
tags: [dsh, cordis, compat, npm, verification]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-11T19:22:22.875002+08:00"
updated_at: "2026-10-11T19:22:22.875002+08:00"
supersedes: [EXPERIENCE-20260820-dsh-lfl-agent-session-ui, EXPERIENCE-20260829-dsh-dsh-home-plugin-verify-schema-boot-repeat-stop]
---