# 记忆近重复聚类报告

- 生成: 2026-09-16T07:09:53.766233+00:00
- 语料: 1493 条 | cos>0.9 簇: 194 覆盖 525 条 | 合并上界(每簇保1): 331
- 精确指纹重复: 0 条

> 本报告只做确定性聚类; 合并取舍归 AI 审定(adjudication.json)→用户批准后执行。

## 簇#1 size=15 cos[max=0.9426 mean=0.9126] 主题≈工具回执,完成声明,如实声明,诚实性
- `MEM-20260828-a2631446` 2026-08-28 v2 :: 最终回答中的完成声明必须与工具执行回执一致；未在回执中出现的成功操作（如处理 HTTP 400 code 1210、切换本地模型）不得声明为已完成。
- `MEM-20260814-564e2288` 2026-08-14 v9 :: 最终回答中不得存在与工具执行回执不符的完成声明；若某操作未成功执行，不得声称已完成。若有工具回执可验证，以回执为准，后续如实声明。
- `MEM-20260815-69fd3160` 2026-08-15 v11 :: 最终回答须与工具回执一致；若存在完成声明与工具回执不符，必须如实声明，不得虚报完成。
- `MEM-20260815-d278970a` 2026-08-15 v1 :: 最终回答中的完成/状态声明必须与工具执行回执一致；系统多次提醒存在不符声明，禁止虚构成功记录。
- `MEM-20260816-46b46ce5` 2026-08-16 v7 :: 系统多次声明-回执校验提醒：最终回答中存在与工具回执不符的完成声明。今后所有完成声明必须与工具实际回执一致，如实区分已完成/未完成，避免因输出断言与工具回执不符触发校验。
- `MEM-20260818-d4fe7e7e` 2026-08-18 v6 :: 声明-回执校验机制：最终回答中的完成声明必须与工具执行回执相符，禁止声明未实际执行的完成事项；不符会被系统提醒并要求更正或重新执行。
- `MEM-20260819-b11a6a26` 2026-08-19 v5 :: 最终回答中的完成声明必须与工具执行回执一致，不得声称回执中不存在的动作（因声明校验提醒而固化）。
- `MEM-20260820-af1d0bf3` 2026-08-20 v2 :: 最终回答中的完成/状态声明必须与工具执行回执一一对应，未执行的动作不得声明已完成（有声明-回执校验提醒）。
- `MEM-20260822-0fdc4742` 2026-08-22 v2 :: 完成声明必须与工具执行回执一致；工具无对应成功回执时不得声明已完成（依据声明-回执校验提醒）。
- `MEM-20260822-99834522` 2026-08-22 v1 :: 系统两次提醒：最终回答中出现了与工具执行回执不符的完成声明；后续必须如实声明，基于真实回执给出结论
- `MEM-20260822-78d919f2` 2026-08-22 v3 :: 最终回答必须依据工具执行回执如实声明完成情况；若存在与工具回执不符的完成声明，系统会触发声明提醒并视为错误，不得虚报完成。
- `MEM-20260822-093001b7` 2026-08-22 v1 :: 2026-08-22 系统多次提醒：最终回答中的完成声明必须与工具回执一致，不得声明本轮及近3轮回执中无对应成功记录的操作或证据；相关记忆/结论需可回溯到工具回执。
- `MEM-20260824-765d4ec1` 2026-08-24 v1 :: 完成声明必须与工具执行回执一致：系统连续 2 次 [声明提醒] 指出最终回答存在回执中无对应成功记录的完成声明；后续需如实声明，避免声明与工具回执不符。
- `MEM-20260828-7d57e2a6` 2026-08-28 v1 :: 最终回答中的完成/进度声明必须以工具执行回执为准；若声明与工具回执不符（如声称某步骤已执行但回执无对应成功记录），会被声明-回执校验提醒并要求后续如实声明、修正表述
- `MEM-20260829-c5318fc8` 2026-08-29 v1 :: 最终回答中的完成声明必须与工具回执一一对应：系统会对声明做回执校验，若声明了回执中不存在的成功动作（如 sudo -k、写入完成等）会触发警告。如实对照 evidence/回执后再声明完成。

## 簇#2 size=13 cos[max=0.9846 mean=0.9395] 主题≈开源仓库,公开面原则,docs/local,index.md
- `MEM-20260829-3b5d6c24` 2026-08-29 v8 :: LFL docs 公开面原则（2026-08-14 确立）：非必要文档不公开，公开仓库只保留运行必需 + 面向使用者的文档；开发过程文档（specs/阶段设计/评估/验收报告/经验记录/内部变更日志）一律本地保留。doc
- `MEM-20260814-c452528d` 2026-08-14 v19 :: 文档公开面原则（2026-08-14 确立）：非必要文档不公开，公开仓库只保留运行必需和面向使用者的文档；开发过程文档（specs/设计/评估/验收报告/经验记录/内部变更日志）一律本地保留，不随开源仓库分发。
- `MEM-20260815-951ae4a2` 2026-08-15 v11 :: docs 公开面原则（2026-08-14 确立）：非必要文档不公开——公开仓库只保留运行必需 + 面向使用者的文档；开发过程文档（specs/阶段设计/评估/验收报告/经验记录/内部变更日志）一律本地保留，不随开源仓库
- `MEM-20260816-f729d541` 2026-08-16 v8 :: docs/INDEX.md 公开面原则（2026-08-14）：非必要文档不公开，开发过程文档（specs/阶段设计/评估/验收报告/经验记录/内部变更日志）一律本地保留，不随开源仓库分发；runtime-sot-wir
- `MEM-20260816-591de933` 2026-08-16 v3 :: 项目文档公开面原则（2026-08-14 确立）：公开仓库只保留运行必需+面向使用者文档；开发过程文档（specs/评估/验收/经验记录/内部变更日志）一律本地保留于 docs/local，不随开源仓库分发。
- `MEM-20260816-e04c9769` 2026-08-16 v1 :: 文档公开面原则：非必要文档不公开；公开仓库只保留运行必需和面向使用者的文档，开发过程文档（specs/阶段设计/评估/验收/经验记录/内部变更日志）一律本地保留于 docs/local。
- `MEM-20260816-48c0a66e` 2026-08-16 v5 :: docs 文档公开面原则（2026-08-14 确立）：非必要文档不公开——公开仓库只保留运行必需+面向使用者文档；开发过程文档（specs/阶段设计/评估/验收报告/经验记录/内部变更日志）一律本地保留（docs/lo
- `MEM-20260816-dcbdb861` 2026-08-16 v2 :: 项目约定（docs/INDEX.md，2026-08-14）：非必要文档不公开——公开仓库只保留运行必需+面向使用者的文档；开发过程文档（specs/阶段设计/评估/验收报告/经验记录/内部变更日志）一律本地保留，不随开
- `MEM-20260816-fce5ac28` 2026-08-16 v1 :: 文档公开面原则（2026-08-14 确立）：非必要文档不公开；开发过程文档（specs/阶段设计/评估/验收报告/经验记录/内部变更日志）一律保留在 docs/local/，不随开源仓库分发；公开仓库只保留运行必需+面
- `MEM-20260817-9f984433` 2026-08-17 v1 :: 文档公开面原则：公开仓库只保留运行必需 + 面向使用者文档；开发过程文档（specs/阶段设计/评估/验收报告/经验记录/内部变更日志）一律本地保留，不随开源仓库分发。
- `MEM-20260817-950817c8` 2026-08-17 v1 :: 本项目文档约定：公开仓库只保留运行必需加面向使用者的文档，specs/设计/评估/经验等过程文档一律本地保留（如 docs/local），不随开源仓库分发。
- `MEM-20260819-89b5a840` 2026-08-19 v1 :: docs 文档公开面原则（2026-08-14 确立，记录于 INDEX.md）：非必要文档不公开——公开仓库只保留运行必需+面向使用者的文档；开发过程文档（specs/阶段设计/评估/验收报告/经验记录/内部变更日志）
- `MEM-20260829-77341665` 2026-08-29 v1 :: 项目文档约定（公开面原则）：非必要文档不公开；开发过程文档（specs/阶段设计/评估/验收/经验记录/内部变更日志）只本地保留，不登记 docs/INDEX.md。RUNTIME-SOT-WIRE 三件套按此原则不登记

## 簇#3 size=7 cos[max=0.9738 mean=0.9308] 主题≈r9重构,append_summary退役,evo-20260811,engine_services
- `MEM-20260904-ec1a6c78` 2026-09-04 v5 :: merge 中 3 处 modify/delete 冲突裁决：src/llm_loop/core/loop/routing.py 与 runtime.py 保留 fix 线 R9 重构的删除（内容已迁入 engine_s
- `MEM-20260909-7732c48b` 2026-09-09 v3 :: merge 冲突裁决结论（56 处 = 36 content + 17 add/add + 3 modify/delete）：① routing.py/runtime.py 保留 fix 线 R9 重构删除（git rm
- `MEM-20260909-5a66e954` 2026-09-09 v3 :: merge 56 处冲突（36 content + 17 add/add + 3 modify/delete）裁决原则：routing.py/runtime.py 保留 R9 重构删除（内容已迁入 engine_serv
- `MEM-20260909-c2b0ff7f` 2026-09-09 v1 :: merge DU 冲突裁决原则：routing.py、runtime.py 保留 fix 线 R9 重构的删除（内容已迁入 engine_services/routing.py、engine_services/runti
- `MEM-20260909-41fa844f` 2026-09-09 v1 :: merge 冲突裁决规则（56 处=36 content+17 add/add+3 modify/delete）：DU 三处中 core/loop/routing.py 与 runtime.py 保留 fix 线 R9 
- `MEM-20260909-177069bb` 2026-09-09 v1 :: merge 冲突裁决原则（DU 三处）：routing.py、runtime.py、test_append_compression.py 均按 fix 线删除裁决（已 git rm）——routing/runtime 是
- `MEM-20260909-bf300df6` 2026-09-09 v3 :: merge 冲突裁决原则（integration 分支）：① DU 三处 git rm——routing.py/runtime.py 是 R9 重构有意删除（内容已迁入 engine_services/routing.p

## 簇#4 size=7 cos[max=0.9612 mean=0.9272] 主题≈token失效,origin/main,git认证失败,push受阻
- `MEM-20260909-07d4ec5a` 2026-09-09 v1 :: git push 认证失败（Invalid username or token，Password authentication not supported），push 前需用户更新凭据；本地 origin/main 引用
- `MEM-20260909-64de18f9` 2026-09-09 v1 :: git push 凭据失效（remote 报 Invalid username or token），本地 origin/main 引用（a4c9f21）为既有引用可用，但最终 push 前需用户更新凭据
- `MEM-20260909-67adbe37` 2026-09-09 v1 :: push 阻塞项：origin 远端凭据失效（Invalid username or token. Password authentication is not supported），最终 push 前需用户更新凭据；本
- `MEM-20260909-f0ba00a7` 2026-09-09 v1 :: git push 认证失败（remote: Invalid username or token），本地 origin/main 引用（a4c9f21）为既有快照可用，但最终 push 前必须由用户更新 Git 凭据/to
- `MEM-20260909-f50d6b5c` 2026-09-09 v1 :: git 远程凭证失效（fetch 报 Invalid username or token），本地 origin/main 引用（a4c9f21）可用于 merge，但最终 push 前需用户更新凭据
- `MEM-20260909-d93f2ea3` 2026-09-09 v1 :: git fetch/push 认证失败（token 失效，报 Invalid username or token），push 前需用户更新凭据；本地 origin/main 引用（a4c9f21）为既有引用可用于 mer
- `MEM-20260909-1ec65b99` 2026-09-09 v1 :: push 阻塞项：git fetch/push 认证失败（token 失效，remote 报 Invalid username or token），本地 origin/main 引用为 a4c9f21（既有引用，merg

## 簇#5 size=6 cos[max=0.976 mean=0.9303] 主题≈复制链接,浏览器听写,分享按钮,sessionurl
- `MEM-20260828-ba817011` 2026-08-28 v4 :: WebUI 文案诚实化裁决：share() 仅复制部署 URL+?session=id（无快照/权限/公开分享后端），分享按钮文案改为「复制会话链接/复制链接」，title 注明受部署鉴权保护非公开分享；听写基于浏览器 
- `MEM-20260909-f7774536` 2026-09-09 v5 :: WebUI 文案与交互裁决：① 分享按钮改为「复制链接」（sessionUrl 仅拼接当前部署 URL + ?session=id，无快照/权限后端，受部署自身鉴权保护，非公开分享）；② 听写按钮明确标注「浏览器听写」（
- `MEM-20260909-815b30ec` 2026-09-09 v2 :: WebUI 分享按钮的事实与裁决：share() 仅复制当前部署 URL + ?session=<id>（buildSessionShareUrl），无快照/权限/公开分享后端，因此文案已从「分享」改为「复制会话链接/复
- `MEM-20260909-3d6d6308` 2026-09-09 v2 :: 文案诚实化裁决：分享按钮实际仅复制当前部署 URL+?session=<id>（受部署自身鉴权保护，无快照/公开分享后端），改为“复制链接”；听写使用浏览器 SpeechRecognition，文案改为“浏览器听写”
- `MEM-20260909-d84fd6a2` 2026-09-09 v1 :: 文案裁决依据：分享按钮 share() 只做 navigator.clipboard.writeText(当前部署 URL + ?session=id)，无快照/权限/公开分享后端，故文案定为'复制链接'；听写基于浏览器
- `MEM-20260909-ed25c5d0` 2026-09-09 v1 :: WebUI 文案诚实化裁决：分享按钮改为“复制链接/复制会话链接”（实际行为仅复制部署 URL + ?session=id，受部署自身鉴权保护，不存在快照/公开分享后端，文案不得暗示公开分享）；听写按钮文案标注“浏览器听

## 簇#6 size=6 cos[max=0.9755 mean=0.9321] 主题≈timeout缺失,osxkeychain,security语法,后台任务
- `MEM-20260908-62cda663` 2026-09-08 v5 :: MCP 沙盒环境陷阱：shell $HOME 是 mcp-console 沙盒目录而非 ~，读用户配置必须用绝对路径；git credential fill/osxkeychain 在沙盒中搜不到 lo
- `MEM-20260908-ada520ea` 2026-09-08 v3 :: 沙盒/环境注意事项：MCP console shell 的 $HOME 是临时沙盒目录而非 ~，查 gh/ssh 配置需用绝对路径；沙盒默认 keychain 搜索列表不含 login.keychain
- `MEM-20260908-d5cc16b4` 2026-09-08 v1 :: MCP console 沙盒环境要点：$HOME 是沙盒临时目录而非 ~（查用户配置/SSH/keychain 必须用绝对路径）；进程默认 keychain 列表不含 login.keychain-db
- `MEM-20260908-8ae81f15` 2026-09-08 v1 :: 沙盒环境陷阱：MCP console shell 的 $HOME 是沙盒目录而非 ~（查用户配置必须用绝对路径）；macOS 无 timeout 命令；security 命令的 keychain 路径必
- `MEM-20260908-55cc4879` 2026-09-08 v2 :: 本机环境要点：MCP console 沙盒 $HOME 是 /var/folders/.../mcp-console/.../home 而非 ~，读用户配置（.ssh/.config/gh/.gitco
- `MEM-20260908-fd257b1f` 2026-09-08 v1 :: 执行环境特性：MCP console 沙盒 $HOME 不是 ~，其默认 keychain 列表不含 login.keychain-db，故 git credential fill（osxkeychai

## 簇#7 size=6 cos[max=0.9649 mean=0.9343] 主题≈noreply,deyi2026,隐私,git
- `MEM-20260817-0518f5bf` 2026-08-17 v4 :: 提交前必须核验 git author/committer 身份为 public-safe 格式 deyi2026 <deyi2026@users.noreply.github.com>，不得以 MCP Console 等
- `MEM-20260825-3d7642f3` 2026-08-25 v2 :: Git 提交身份约定（public-safe）：author/committer 统一为 deyi2026 / deyi2026@users.noreply.github.com（noreply 格式），提交前需核验不泄
- `MEM-20260908-6011fc77` 2026-09-08 v2 :: git 提交身份必须使用公共安全 noreply 格式：deyi2026 <deyi2026@users.noreply.github.com>（author/committer 均需在提交前核验为此格式）。
- `MEM-20260908-0b262a8b` 2026-09-08 v5 :: Git 提交身份要求 public-safe noreply 格式：deyi2026 <deyi2026@users.noreply.github.com>，author 与 committer 须一致，提交前需核验
- `MEM-20260909-680c5495` 2026-09-09 v1 :: Git 提交身份使用公共安全 noreply 格式：deyi2026 <deyi2026@users.noreply.github.com>
- `MEM-20260909-7f2594a8` 2026-09-09 v1 :: Git 提交身份使用公共安全 noreply 格式：作者/提交者均为 deyi2026 <deyi2026@users.noreply.github.com>，不暴露真实邮箱

## 簇#8 size=6 cos[max=0.9318 mean=0.9152] 主题≈fast-forward,fresh-checkout,7589dbd,合并标准
- `MEM-20260908-63c2663f` 2026-09-08 v1 :: 用户批准的 main 合并决策（2026-09-08）：① 将 1f991a9 纯 fast-forward 推到 main；② no-ff 合并 fix/fresh-checkout-reproducibility（7
- `MEM-20260908-dc9823a9` 2026-09-08 v2 :: 用户授权的并 main 计划（标准：已在运行稳定的更新才并入 main）：① 将 main 纯 fast-forward 到 1f991a9（feature/qwen-runtime-erdc-public-202609
- `MEM-20260908-1ccc9e17` 2026-09-08 v3 :: 用户合并策略（2026-09-08 确立）：已在 integration 运行稳定的更新值得更新到 main。本次授权执行两步：① 将 feature/qwen-runtime-erdc-public-20260908（
- `MEM-20260908-872aec8d` 2026-09-08 v4 :: 2026-09-08 用户授权并 main（判定标准：已在 integration/input184k-output16k-20260908 运行且稳定的更新才并 main）：① feature/qwen-runtime
- `MEM-20260908-cb955b14` 2026-09-08 v1 :: 用户决策（按建议执行）：将已运行稳定的更新合并到 main——① 纯 fast-forward 把 main 推到 1f991a9（feature/qwen-runtime-erdc-public-20260908，其功
- `MEM-20260908-3544612b` 2026-09-08 v1 :: 用户批准的 main 合并标准与执行计划（2026-09-08）：标准='已在运行（integration 分支）且稳定的更新值得并 main'。批准执行：① main 纯 fast-forward 推到 1f991a9

## 簇#9 size=5 cos[max=0.9726 mean=0.9331] 主题≈b1-b4,薄移植,goal-20260909-27053104,8903 验收
- `MEM-20260817-ee79c3b2` 2026-08-17 v21 :: 活跃目标 GOAL-20260909-27053104：Web 后端最小闭环 B1-B4，在 llm-first-loop main 上薄移植（不复活整包旧后端），补齐 UI 已暴露但后端缺失的附件最近列表/worksp
- `MEM-20260909-2df2568f` 2026-09-09 v12 :: LFL 活跃目标 GOAL-20260909-27053104：Web 后端最小闭环 B1-B4，在 llm-first-loop main 上补齐 UI 已暴露但后端缺失的功能（附件最近列表/workspace 导入、
- `MEM-20260909-91250946` 2026-09-09 v7 :: LFL 活跃目标 GOAL-20260909-27053104：Web 后端最小闭环 B1-B4，原则为'不复活整包旧后端，只做薄移植；程序只提供事实不做策略'。任务：B1 附件闭环(doing)、B2 session 
- `MEM-20260910-3048755c` 2026-09-10 v1 :: 活跃目标 GOAL-20260909-27053104：Web 后端最小闭环 B1-B4，在 llm-first-loop main 上补齐 UI 已暴露但后端缺失的功能（附件最近列表/workspace 导入、sess
- `MEM-20260911-0dec12d1` 2026-09-11 v1 :: LFL 当前活动目标 GOAL-20260909-27053104：Web 后端最小闭环 B1-B4——在 llm-first-loop main 上补齐 UI 已暴露但后端缺失的附件最近列表/workspace 导入、

## 簇#10 size=5 cos[max=0.9694 mean=0.9507] 主题≈授权,快照树删除,merge origin/main,4红修复延后
- `MEM-20260823-1fa8e0ee` 2026-08-23 v20 :: 用户已授权三项处置（2026-09-09）：① 整合策略采用 merge origin/main 方案（否决 rebase 与直接推分支）；② 4 项 working_set 预存红修复放在 merge 之后进行（避免冲
- `MEM-20260908-ad988c74` 2026-09-08 v4 :: 用户三项授权（2026-09-09）：① push 整合采用 merge origin/main 方案（否决 rebase：两线存在同内容异哈希重复提交、需重放约 21 个提交；否决直接推分支：只推迟不解决问题）；② 4
- `MEM-20260909-77a6c25a` 2026-09-09 v4 :: 用户三项授权（2026-09-09）：① merge origin/main 整合策略按建议流程执行；② 4 项 working_set 预存红放在 merge 后修复（避免冲突解决期间测试噪音）；③ 快照树 rm 已批
- `MEM-20260909-8fe80b1b` 2026-09-09 v3 :: 用户 2026-09-09 三项授权决策：① push 整合采用 merge origin/main 方案（不用 rebase——两线存在同内容异哈希的重复提交，rebase 需重放大量提交且反复撞冲突；不用直接推分支—
- `MEM-20260909-e9b06582` 2026-09-09 v1 :: 用户三项授权（2026-09-09）：① push 整合策略采用 merge origin/main（否决 rebase：两线存在大量同内容异哈希重复提交，重放会反复撞冲突；否决直接推分支：只推迟不解决）；② 4 项 w

## 簇#11 size=5 cos[max=0.9673 mean=0.932] 主题≈agents.md,准入不对称,治理北极星,处置表
- `MEM-20260909-b3462011` 2026-09-09 v2 :: AGENTS.md 已增补 Admission asymmetry 条款（2026-09-09）：依据 docs/subsystem-disposition-20260909.md 治理北极星——程序供证据/工具/回路、
- `MEM-20260909-43676e5c` 2026-09-09 v14 :: 治理北极星判据（docs/subsystem-disposition-20260909.md）：程序供证据、供工具、供回路，决策留给模型；放大模型智力的（证据/记忆/工具/反馈）保留加强，替代模型决策的（硬门禁/启发式裁
- `MEM-20260909-c241681e` 2026-09-09 v7 :: 治理北极星判据（docs/subsystem-disposition-20260909.md）：程序供证据、供工具、供回路，决策留给模型；每个子系统以「放大模型智力还是替模型做决定」为取舍标准，每处门禁必须有「模型可举证
- `MEM-20260909-cd632077` 2026-09-09 v5 :: llm-first-loop 项目治理北极星（2026-09-09 定于 docs/subsystem-disposition-20260909.md）：程序供证据、供工具、供回路，决策留给模型；子系统判据为「放大模型智
- `MEM-20260909-6400494f` 2026-09-09 v1 :: 治理北极星判据（docs/subsystem-disposition-20260909.md）：程序供证据/工具/回路，决策留给模型——子系统放大模型智力则保留加强，替代模型做决定（硬门禁/启发式裁决/静默截断/兼容包袱

## 簇#12 size=5 cos[max=0.9596 mean=0.937] 主题≈误删,会话文件,教训,清理逻辑
- `MEM-20260811-bf1a1ea7` 2026-08-11 v1 :: 误删会话文件教训：CLI fork 验证时清理逻辑用 `ls -t | head -1` 取最新文件，fork 失败未创建新文件导致误删现有会话 data/sessions/5b84a203.json（后由运行中内存自动
- `MEM-20260811-85ed3ab9` 2026-08-11 v1 :: 教训：清理临时文件时用 `ls -t | head -1` 推断“新创建文件”不可靠——fork 失败未创建新文件时，会误删最新修改的现有会话（曾误删 data/sessions/5b84a203.json，后由运行中内
- `MEM-20260811-26732b69` 2026-08-11 v1 :: 误删会话文件事件教训：CLI fork 验证时清理逻辑有 bug，误删 data/sessions/5b84a203.json（当前会话文件），因当前 run 已加载会话内存，本轮保存时自动恢复（197 条消息完整）；此
- `MEM-20260811-c54bb631` 2026-08-11 v1 :: 2026-08-11 验证 CLI fork 时清理逻辑 bug 误删 data/sessions/5b84a203.json（当前会话），后因引擎内存持有会话自动恢复（197条消息无损失）。教训：清理临时文件时避免用 
- `MEM-20260811-6c2afbef` 2026-08-11 v1 :: 操作教训：验证 CLI fork 命令时，因清理逻辑用 ls -t | head -1 取最近文件，fork 失败未创建新文件导致误删当前会话文件 data/sessions/5b84a203-3d1b-4b56-91d

## 簇#13 size=5 cos[max=0.9577 mean=0.935] 主题≈已知红清单,known-reds-20260909,预存红,防复发
- `MEM-20260904-09f79770` 2026-09-04 v35 :: 已知红清单约定（docs/known-reds-20260909.md）：预存红须显式登记，每项必须走「修复 或 显式接受」二选一，禁止用扩基线方式让红卫兵变绿。清单含 origin/main 基线 8 项（复核后 7 
- `MEM-20260909-df7d3d50` 2026-09-09 v8 :: 已知红清单约定（docs/known-reds-20260909.md）：预存红不是放任，每项必须走「修复 或 显式接受」二选一，禁止用扩基线的方式让红卫兵变绿；该清单是测试分层防复发机制的一部分（对应 docs/sub
- `MEM-20260909-1d2d768b` 2026-09-09 v2 :: 已知红清单建于 docs/known-reds-20260909.md：§1 origin/main 基线 8 项预存红（复核后 7 项转绿、1 项退役）；§2 四项 working_set HEAD 预存红。维护约定：
- `MEM-20260909-1f18db1c` 2026-09-09 v2 :: llm-first-loop-mirror 已建立已知红清单 docs/known-reds-20260909.md：§1 origin/main 基线预存红 8 项（复核后 7 绿 1 退役）；§2 working_s
- `MEM-20260909-9eef8543` 2026-09-09 v1 :: 已知红清单 docs/known-reds-20260909.md 的维护约定：预存红不是放任，每项必须走「修复 或 显式接受」二选一，禁止用扩基线方式让红卫兵变绿；清单含 origin/main 基线 8 项（其中 7

## 簇#14 size=5 cos[max=0.9447 mean=0.9342] 主题≈editable安装,deploy-capability-96a,worktree,venv
- `MEM-20260814-15b9486f` 2026-08-14 v8 :: R1级关键事实：mirror 主 .venv 的 editable 安装指向 .worktrees/deploy-capability-96a-20260915/src（第三条工作线，既非 baseline 也非 can
- `MEM-20260817-d1dfc5a6` 2026-08-17 v8 :: R1 级环境陷阱：mirror 主 .venv 的 editable 安装指向第三条工作线 .worktrees/deploy-capability-96a-20260915/src（既非 baseline 也非 can
- `MEM-20260903-502249a2` 2026-09-03 v3 :: R1 级风险事实：mirror 主工作区 .venv 的 editable 安装指向 .worktrees/deploy-capability-96a-20260915/src（第三条工作线），既非 baseline 也
- `MEM-20260915-bf8aaee8` 2026-09-15 v1 :: R1 级风险事实：mirror 主 .venv 的 editable 安装指向 .worktrees/deploy-capability-96a-20260915/src（第三条工作线，既非 baseline 也非 ca
- `MEM-20260916-b2866621` 2026-09-16 v1 :: 关键环境陷阱：mirror 主 .venv 的 editable 安装指向 .worktrees/deploy-capability-96a-20260915/src（第三条工作线，非 baseline/candidat

## 簇#15 size=5 cos[max=0.9424 mean=0.9238] 主题≈fake-ip,网络环境,surge,clash
- `MEM-20260810-39e9984b` 2026-08-10 v86 :: 用户网络环境：代理为 Surge/Clash fake-ip 模式（目标域名解析到 198.18/15 假 IP 段），web_fetch 按代理通道放行；WEB_FETCH_BLOCK_FAKE_IP=1 可恢复严格拦
- `MEM-20260813-e64cae62` 2026-08-13 v29 :: 网络环境事实：本机代理为 fake-ip 模式（198.18/15 段，Surge/Clash），目标域名常解析到假 IP 已按代理通道放行，WEB_FETCH_BLOCK_FAKE_IP=1 可恢复严格拦截。docs.
- `MEM-20260816-efdd1727` 2026-08-16 v1 :: 环境特性：目标解析为代理假 IP 段（198.18/15，Surge/Clash fake-ip 模式），WEB_FETCH_BLOCK_FAKE_IP=1 可恢复严格拦截。
- `MEM-20260907-40f8d583` 2026-09-07 v1 :: 用户网络环境运行 Surge/Clash 类代理（fake-ip 模式，域名解析到 198.18/15 假 IP 段）；抓取工具对假 IP 段默认按代理通道放行，设置 WEB_FETCH_BLOCK_FAKE_IP=1 
- `MEM-20260911-c3d9b136` 2026-09-11 v2 :: 本机网络环境为 Surge/Clash fake-ip 代理模式（198.18/15 段），web 抓取按代理通道放行，设 WEB_FETCH_BLOCK_FAKE_IP=1 可恢复严格拦截；docs.anthropic

## 簇#16 size=4 cos[max=0.9835 mean=0.9511] 主题≈toolmode-off,66e41958,快照树,已删除
- `MEM-20260813-d3a4c463` 2026-08-13 v13 :: 快照树 data/runtime/toolmode-off-66e41958ffca/src（7.8M，对应 2026-09-03 commit 66e41958 的 src 快照副本，未被 git 跟踪）经用户批准已 
- `MEM-20260909-395114ed` 2026-09-09 v6 :: 快照树 data/runtime/toolmode-off-66e41958ffca 是 commit 66e41958（2026-09-03）时刻的未跟踪 src 快照（git 未跟踪、无进程引用），经用户批准于 20
- `MEM-20260909-55501c43` 2026-09-09 v1 :: 快照树 data/runtime/toolmode-off-66e41958ffca 是 2026-09-03 对 commit 66e41958 的 src 快照（未纳入 git 追踪，无引用），经用户批准已删除其 s
- `MEM-20260909-62897492` 2026-09-09 v1 :: 快照树 data/runtime/toolmode-off-66e41958ffca/src（7.8M，2026-09-03 生成）经核实与 commit 66e41958 的 src 完全一致、未被 git 跟踪、无进

## 簇#17 size=4 cos[max=0.9755 mean=0.9523] 主题≈merge,整合策略,56冲突,integration/fix-restart-continuity-into-main
- `MEM-20260909-44237d60` 2026-09-09 v1 :: push 整合策略定为 merge origin/main（2026-09-09 用户授权）：不选 rebase（两线存在大量同内容异哈希重复提交，重放会反复撞冲突）、不选直接推分支（只推迟问题）；merge 在新分支 
- `MEM-20260909-dc2c56b0` 2026-09-09 v6 :: 用户批准 push 整合策略采用 merge origin/main（否决 rebase：两线存在大量同内容异哈希重复提交，重放 21 个 fix 线提交会反复撞冲突；否决直接推分支：只推迟不解决问题）。合并在新分支 i
- `MEM-20260909-e0c9a56f` 2026-09-09 v1 :: Push 整合策略（2026-09-09 用户确认）：采用 merge origin/main（否决 rebase——两线存在大量同内容异哈希重复提交会反复撞冲突；否决直接推分支——只推迟不解决）。在集成分支 integ
- `MEM-20260909-18112c8c` 2026-09-09 v2 :: 用户批准 push 整合策略为 merge origin/main（2026-09-09）：在集成分支 integration/fix-restart-continuity-into-main 上执行；不选 rebase

## 簇#18 size=4 cos[max=0.9649 mean=0.9291] 主题≈a078972,glm-minimax-1,无效数据,request.usage
- `MEM-20260829-032ec7f6` 2026-08-29 v6 :: glm-minimax-1 四组结果均为 rounds=0、tokens_in=0、tokens_out=0，不能作为效果数据；a078972 修复了 event_logs request.usage 实测采集口径。
- `MEM-20260829-f7279c88` 2026-08-29 v1 :: glm-minimax-1旧summary四组结果均rounds=0/tokens_in=0/tokens_out=0，不能作为效果数据；镜像a078972提交修复event_logs/request.usage实测采集
- `MEM-20260829-3f0bdf56` 2026-08-29 v1 :: glm-minimax-1 的 summary 数据全部无效（rounds=0、tokens_in=0、tokens_out=0），不能作为效果数据；a078972 修复了 event_logs/request.usag
- `MEM-20260829-55ab5d70` 2026-08-29 v1 :: glm-minimax-1 的 summary 数据无效（rounds=0/tokens_in=0/tokens_out=0），不能作为效果数据；glm-minimax-2 已跑通：四条 run rounds>0、tok

## 簇#19 size=4 cos[max=0.9648 mean=0.9568] 主题≈unix哲学,linux,语义接口,ai交互方向
- `MEM-20260907-36b7a2d7` 2026-09-07 v1 :: 用户核心观点：AI直接操作GUI/UI效率太低、不是AI的发展方向；正确方向是操作系统层面把能力暴露为机器可语义化的接口（CLI/语义API与人机交互结合）；认为Linux的Unix哲学（文本管道、一切皆文件、可脚本化）
- `MEM-20260907-a69ed64a` 2026-09-07 v1 :: 用户的核心技术观点：AI直接操作GUI（computer use）效率太低、不是AI的发展方向；正确方向是操作系统层面将CLI/语义接口与人类交互结合改进；认为Linux（Unix哲学：文本管道、一切皆文件、可脚本化、D
- `MEM-20260810-dcd005c5` 2026-08-10 v3 :: 用户技术观点：AI 操作 GUI/UI 效率太低、落后，不是 AI 的发展方向；正确方向是操作系统层面 CLI 与人类交互相结合的改进（让界面具备机器可语义化接口）；用户认为 Linux 的 Unix 哲学（文本管道、组
- `MEM-20260907-763d9f8a` 2026-09-07 v1 :: 用户核心观点：AI 做 GUI 操作（截图+点击）效率太低、太落后，不是 AI 的发展方向；正确方向是操作系统层面暴露语义化能力接口（CLI/语义层与人类交互结合），人与 agent 各用各的带宽；用户直觉 Linux（

## 簇#20 size=4 cos[max=0.9642 mean=0.9357] 主题≈injection_span,test_continuity,冲突裁决,err1210
- `MEM-20260828-08c7f8f4` 2026-08-28 v3 :: merge 冲突裁决惯例：SlotKind/parse_aggregated_slots 已由 fix 线迁至 injection_span.py，main 侧旧路径 err1210 引用一律取 ours；fix 线严格
- `MEM-20260909-56d8da7b` 2026-09-09 v1 :: merge AA 冲突裁决模式：AGENTS.md、docs/continuity.md、scripts/continuity.py 等为 fix 线严格超集取 ours；SlotKind/parse_aggregate
- `MEM-20260909-10e2c9b3` 2026-09-09 v1 :: merge 冲突解决中 AA 文件的裁决模式：numstat 显示 ours 比 theirs 多且 theirs 无新增（如 AGENTS.md 0+22）→ fix 线是严格超集，取 ours；SlotKind/pa
- `MEM-20260909-c0617908` 2026-09-09 v3 :: AA 冲突裁决模式：AGENTS.md、docs/continuity.md、scripts/continuity.py 为 fix 线严格超集，取 ours；SlotKind/parse_aggregated_slot

## 簇#21 size=4 cos[max=0.957 mean=0.9274] 主题≈funcname,diff 校验,hunk header 注解,归一化比对
- `MEM-20260908-01f030df` 2026-09-08 v1 :: 远端 diff 校验方法：GitHub API 返回的 diff 与本地 git diff 可能因 @@ hunk 头的函数上下文注解不同而字节不等（本地 git 与 GitHub 的 funcname 检测算法不同），
- `MEM-20260908-19438dfd` 2026-09-08 v4 :: diff 比对知识：本地 git diff 与 GitHub API 返回的 diff 可能因 hunk 头部注解（@@ ... @@ 后的函数上下文标签）不同而字节数不等（两者 funcname 检测算法不同），剥离注
- `MEM-20260908-abfae3fb` 2026-09-08 v1 :: GitHub 远端 API 的 diff 与本地 git diff 可能差几十字节：仅 hunk 头 @@ 注解（funcname 上下文标签）不同，因两边函数名检测算法差异；剥离注解后逐字节比对一致即内容相同
- `MEM-20260908-df7ee71e` 2026-09-08 v1 :: 本地 git diff 与 GitHub API 返回的 diff 可能存在 52 字节级别的差异，来源是 hunk 头注解（两侧 funcname 检测算法不同，@@ 行后的函数上下文标签）；剥离注解后逐字节一致即视为

## 簇#22 size=4 cos[max=0.9529 mean=0.9288] 主题≈运行一致性,proc_version,change_log,进程版本
- `MEM-20260811-5e8d2a71` 2026-08-11 v1 :: EVO-20260811-f94e5306“运行一致性保障”已实施：introspection/proc_version.py 提供 record_process_start/get_process_versions/r
- `MEM-20260811-cedf0b7a` 2026-08-11 v1 :: 运行一致性保障机制（EVO-20260811-f94e5306）已由并行进程实施并通过验证：introspection/proc_version.py 提供 record_process_start/get_proces
- `MEM-20260811-69ad5b77` 2026-08-11 v1 :: EVO-20260811-f94e5306（运行一致性保障机制）已实施：proc_version.py 记录进程启动时间+git HEAD，architecture_status 展示进程版本，change_log 记录
- `MEM-20260811-c25cafd4` 2026-08-11 v1 :: EVO-20260811-f94e5306（运行一致性保障）已 accepted 并实施（并行进程完成）：introspection/proc_version.py 提供 record_process_start/get

## 簇#23 size=4 cos[max=0.9462 mean=0.9198] 主题≈method learning,2026-09-09,b1-b4,git审查
- `MEM-20260909-915dbcf0` 2026-09-09 v1 :: 2026-09-09 审查结论：单日约 30 commit 分三条线——① Web 后端闭环 B1-B4（496cf56/cecb6a9/d59169f）② Method Learning v1 seed+runtime
- `MEM-20260909-da8b9baa` 2026-09-09 v4 :: 2026-09-09 单日约 30 个提交分三条线：(1) Web 后端闭环 B1-B4（附件 recent+导入 496cf56、session jobs+kill 与 continuity 机械事实 cecb6a9、
- `MEM-20260909-cfa907d8` 2026-09-09 v3 :: 2026-09-09 LFL 单日约 30 个 commit 分三线：①Web 后端闭环 B1-B4（496cf56 附件闭环 / cecb6a9 B2+B3 / d59169f B4 manifest）；②Method
- `MEM-20260911-d6b70b9f` 2026-09-11 v1 :: 2026-09-09 审查结论：当天约 30 个 commit 分三线——Web 后端闭环 B1-B4（496cf56 附件 recent+导入 / cecb6a9 session jobs+kill+continuit

## 簇#24 size=4 cos[max=0.9405 mean=0.9229] 主题≈§12.1,downloads,文档路径,v1.1设计文档
- `MEM-20260915-efc3acc7` 2026-09-15 v1 :: LFL 设计文档 v1.1 权威路径为 ~/Downloads/LFL_执行力优化_需求设计_v1.1_20260915.md；§12.1 不在 evals/pilot/GOVERNANCE.v1.md
- `MEM-20260915-80947c75` 2026-09-15 v5 :: 《LFL 执行力优化需求设计》v1.1 权威原文位于 ~/Downloads/LFL_执行力优化_需求设计_v1.1_20260915.md（775 行，sha256 577ef08e…），§12.1/
- `MEM-20260915-f0299d12` 2026-09-15 v2 :: 《LFL 执行力优化需求设计》v1.1 真实路径：~/Downloads/LFL_执行力优化_需求设计_v1.1_20260915.md（775 行，sha256 577ef08e…）。§12.1 阶段
- `MEM-20260915-17a3b4e5` 2026-09-15 v1 :: LFL 执行力优化设计 v1.1 真实路径为 ~/Downloads/LFL_执行力优化_需求设计_v1.1_20260915.md（775 行，sha256 577ef08e…），§12.1 阶段表/

## 簇#25 size=4 cos[max=0.9303 mean=0.92] 主题≈spawn_subagent,experience-20260903,get_tool_schema,tool.eligibility
- `MEM-20260903-ff7e29cd` 2026-09-03 v1 :: 2026-09-03 breaker 拦截裁决（call_900b930c8c0542919f366360）：get_tool_schema('spawn_subagent') 首次 SUCCESS 后 x3/x4/x5
- `MEM-20260903-0a5de1a0` 2026-09-03 v1 :: breaker 机制裁决结论（call_900b930c8c0542919f366360 案）：x3-x5 对无参数变化的重复 get_tool_schema 单次拦截局部正确，但系统级错误——breaker 语义是"否
- `MEM-20260903-309127ca` 2026-09-03 v1 :: Loop breaker 语义缺陷裁决（2026-09-03，call_900b930c8c0542919f366360）：单次拦截局部正确（重复取同一 schema 无新信息，x3/x4/x5 间无新用户指令与参数变化
- `MEM-20260903-ab0f0640` 2026-09-03 v1 :: loopbreaker 裁决结论（2026-09-03，call_900b930c8c0542919f366360）：x5 单次拦截局部正确（无参数变化时重复取同一 schema 无新信息），但 x3→x5 是系统性错误

## 簇#26 size=4 cos[max=0.9262 mean=0.9117] 主题≈rigor.py,program.md,optional,装饰品
- `MEM-20260910-9ebc90d3` 2026-09-10 v15 :: rigor.py（autoresearch-mlx，151行）裁决结论：是装饰品。program.md 全文零次提及 rigor.py；全仓库引用仅 README 的 'Rigorous keep/discard (op
- `MEM-20260910-c0e70acc` 2026-09-10 v9 :: 已核实结论：rigor.py 在 autoresearch-mlx 中是'装饰品'——program.md（115行）全文零次提及 rigor.py，全仓库引用仅 README 的 'Rigorous keep/disc
- `MEM-20260911-877b009e` 2026-09-11 v1 :: 对 autoresearch-mlx 的裁决：rigor.py 是'装饰品'——program.md 全文零次提及 rigor.py；全仓库引用仅 README 章节（标题自带 optional）和 .gitignore
- `MEM-20260911-5fa4c6d9` 2026-09-11 v1 :: 对 autoresearch-mlx 仓库的完整审计结论：rigor.py 是'装饰品'——program.md 全文零次提及它，全仓库仅 README 的 'Rigorous keep/discard (optiona

## 簇#27 size=4 cos[max=0.9194 mean=0.9155] 主题≈模型切换,纯追加,前缀稳定,_inject_switch_notice
- `MEM-20260818-9c4d3767` 2026-08-18 v2 :: 模型切换前缀不变（字节层面）保证机制：.env 配 HISTORY_MAX_CHARS=1000000 + TOOL_TRIM_ENABLED=false + TOOL_TAIL=0，靠纯追加不裁切保持前缀稳定；切换通知
- `MEM-20260821-71bb51ee` 2026-08-21 v3 :: 2026-08-22 确认前缀稳定方案：当前 .env 配置（HISTORY_MAX_CHARS=1000000、TOOL_TRIM_ENABLED=false、TOOL_TAIL=0）保证历史纯追加不裁切；模型切换（c
- `MEM-20260822-e74e4572` 2026-08-22 v1 :: 2026-08-22 确认当前前缀稳定配置：HISTORY_MAX_CHARS=1000000、TOOL_TRIM_ENABLED=false、TOOL_TAIL=0；模型切换前缀不变依赖纯追加/不裁切策略（两全方案已回
- `MEM-20260822-2b9ad98a` 2026-08-22 v1 :: 2026-08-22 确认模型切换前缀不变机制：commit c7e91fe `_inject_switch_notice` 在切换时额外追加一条切换通知（任务目标+AI 最近进度+切换不改变任务），不修改已有前缀字节。

## 簇#28 size=4 cos[max=0.9187 mean=0.912] 主题≈p0-1,cache-hit-governance,final-execution-plan-cache-hit-governance,cache_hit_show_in_answer
- `MEM-20260820-02f62ad4` 2026-08-20 v5 :: docs/FINAL-EXECUTION-PLAN-cache-hit-governance.md 为定稿执行方案（三方综合），执行方=镜像 LFL（本 agent，工作区 ~/Project/llm-
- `MEM-20260820-ec95c284` 2026-08-20 v4 :: 按 docs/FINAL-EXECUTION-PLAN-cache-hit-governance.md 定稿方案实施缓存命中率治理，执行方为镜像 LFL（当前工作区）；从 P0-1 开始：config.py 中 cach
- `MEM-20260820-3ea18f00` 2026-08-20 v2 :: 缓存命中治理执行方案已定稿并确认可执行：docs/FINAL-EXECUTION-PLAN-cache-hit-governance.md（2026-08-20），执行方=镜像 LFL（~/Projec
- `MEM-20260820-421a0346` 2026-08-20 v1 :: FINAL-EXECUTION-PLAN-cache-hit-governance.md 已定稿并确认适合执行，执行方为镜像 LFL。P0-1：cache_hit_show_in_answer 默认值 True→Fals

## 簇#29 size=3 cos[max=0.9805 mean=0.9746] 主题≈飞书,p2p,chat_id,open_id
- `MEM-20260811-40382f5f` 2026-08-11 v1 :: 飞书 p2p 私聊消息事件中 chat_id 为空导致回复发送失败，已修复：FeishuMessage.__post_init__ 在 chat_id 为空时自动使用 open_id + receive_id_type=
- `MEM-20260811-6feb58f9` 2026-08-11 v1 :: 飞书 p2p 私聊消息的 chat_id 为空导致回复发送失败；修复于 2026-08-11 落地源码：FeishuMessage.__post_init__ 在 chat_id 为空时自动改用 open_id + re
- `MEM-20260811-43440c37` 2026-08-11 v1 :: 飞书私聊(p2p)消息事件中 chat_id 为空导致回复发送失败；修复方案：FeishuMessage.__post_init__ 自动用 open_id 作为回复目标（chat_id 非空用 chat_id，为空用 

## 簇#30 size=3 cos[max=0.9759 mean=0.9388] 主题≈.smx,运行时数据,gitignore,lfl仓库
- `MEM-20260904-adfd6e09` 2026-09-04 v19 :: .smx/ 目录是 SMX 运行时数据（快照/回执/运行日志），不得提交入库，需有 .gitignore 规则（v0.6.13 发布时规则缺失，正在补）
- `MEM-20260912-ce531df0` 2026-09-12 v2 :: .smx/ 目录是 SMX 运行时数据（快照/回执/日志），不得提交入库，需加入 .gitignore 规则
- `MEM-20260912-e97b0904` 2026-09-12 v4 :: LFL 仓库中 `.smx/` 目录是运行时数据（快照/回执等），不得提交入库，需加入 .gitignore（2026-09-12 检查时该规则尚缺失）

## 簇#31 size=3 cos[max=0.9759 mean=0.9658] 主题≈飞书,凭证,.feishu.env,cli_a9240f3f7cb85cc4
- `MEM-20260811-8fe63120` 2026-08-11 v1 :: llm-first-loop 飞书使用独立 app（FEISHU_APP_ID=cli_a9240f3f7cb85cc4），不能用 SYAGI 的 cli_a925220d；正确凭证已写入项目 .feishu.env（6
- `MEM-20260811-8c3950ab` 2026-08-11 v1 :: llm-first-loop 使用独立飞书 app（cli_a9240f3f7cb85cc4），勿用 SYAGI 的 cli_a925220d；正确凭证存于项目 .feishu.env（权限600、gitignore）。
- `MEM-20260811-1a0d2d4b` 2026-08-11 v1 :: llm-first-loop 飞书独立 app 凭证为 cli_a9240f3f7cb85cc4（非 SYAGI 的 cli_a925220d）；已创建 .feishu.env（600权限、.gitignore）保存凭证

## 簇#32 size=3 cos[max=0.9733 mean=0.94] 主题≈goal-20260827-27d22a8e,审计报告,分批落地,prompt projection
- `MEM-20260819-a505e9dd` 2026-08-19 v10 :: 2026-08-27 创建目标 GOAL-20260827-27d22a8e：处理《LLM-First Core Loop 审计与优化建议报告》。流程=事实核验→提交演进建议（Prompt Projection & Co
- `MEM-20260827-86c605c6` 2026-08-27 v2 :: 2026-08-27 审计报告《LLM-First Core Loop 审计与优化建议报告》经三方核验（GPT 原审 × 主控核验 × CodeArts 复核）实质收敛后获用户审批，目标 GOAL-20260827-27
- `MEM-20260827-a8808967` 2026-08-27 v2 :: 已创建目标 GOAL-20260827-27d22a8e：处理 2026-08-27《LLM-First Core Loop 审计与优化建议报告》。流程：完成事实核验 → 提交演进建议 → 用户审批后按镜像协议分批落地（

## 簇#33 size=3 cos[max=0.9704 mean=0.9407] 主题≈semantictaskstate,test_append_compression,d03c913,append_summary 退役
- `MEM-20260909-262936ab` 2026-09-09 v2 :: append_summary（追加式压缩摘要）功能已在 fix 线 d03c913 边界重构中退役（src 零残留）；main 侧新增的 2 个决策线测试语义已由 fix 线 test_cognitive_compile
- `MEM-20260909-1e9a1b18` 2026-09-09 v2 :: llm-first-loop-mirror 的 append_summary 追加式压缩功能在 fix 线 d03c913 边界重构中有意退役（src 零残留、conftest 已清 APPEND_COMPRESSION
- `MEM-20260909-0c7d626b` 2026-09-09 v4 :: append_summary（追加式压缩摘要）功能在 fix 线 d03c913 边界重构中有意退役（src 零残留、conftest 已清 APPEND_COMPRESSION 泄漏）；merge 中 DU 冲突的 t

## 簇#34 size=3 cos[max=0.9699 mean=0.9626] 主题≈make-then-break,未提交改动,registry 栈化,learning-plane-p0a
- `MEM-20260810-ae782eae` 2026-08-10 v6 :: 2026-09-10 分支 feature/learning-plane-p0a-20260910（HEAD 8e589de）存在未提交改动：registry 工具栈化（_StackStore per-name 栈、栈顶
- `MEM-20260818-de7801ac` 2026-08-18 v8 :: 当前分支 feature/learning-plane-p0a-20260910（HEAD 8e589de），2026-09-10 存在大量未提交改动：registry 工具栈化（_StackStore per-name
- `MEM-20260820-01237716` 2026-08-20 v5 :: 分支 feature/learning-plane-p0a-20260910 上有大量未提交改动（16 文件 +545 −132）：registry.py 工具栈化（_StackStore per-name 栈语义、un

## 簇#35 size=3 cos[max=0.9699 mean=0.9468] 主题≈评测本地跑,secrets,ci secrets,用户决策
- `MEM-20260815-ddba3768` 2026-08-15 v3 :: 用户决策：CI 不配置 secrets，评测在本地运行；docs/metrics/ 为本地产物不入库。
- `MEM-20260815-a789ee85` 2026-08-15 v1 :: 用户决策：CI 不配置 secrets，评测在本地跑；docs/metrics/ 不入库
- `MEM-20260815-34b92c73` 2026-08-15 v1 :: 评测决策：不配置 CI secrets，评测在本地运行；docs/metrics/ 不入库（commit 264d7a7 用户决策 A）。

## 簇#36 size=3 cos[max=0.9692 mean=0.9537] 主题≈jq聚合,jq,jsonl,聚合
- `MEM-20260825-60a8634b` 2026-08-25 v1 :: 对 jsonl 大文件做分析时，应分批用 jq 聚合（类型分布、role 分布、时间跨度、reasoning 长度、projection_guard 触发、truncated 计数等），避免单次 head 输出过大被截断
- `MEM-20260826-1c169749` 2026-08-26 v1 :: 分析 jsonl 大文件时应分批用 jq/python 聚合统计（事件类型分布、时间跨度、行数等），避免单次 head 输出过大被截断（100K+ 字符会截断）；小文件（<10 行）可直接 read_file 全文。此方
- `MEM-20260827-ff8f76a0` 2026-08-27 v1 :: 经验：分析 jsonl 大文件时应分批用 jq/python 聚合（类型分布、role 分布、时间跨度、reasoning 长度、projection_guard 触发、truncated 计数等），避免单次 head 

## 簇#37 size=3 cos[max=0.969 mean=0.9633] 主题≈演进建议,evolution_complete,evo-20260822-9fde48f1,evo-20260822
- `MEM-20260827-fe075f95` 2026-08-27 v1 :: 存在executing演进建议EVO-20260822-9fde48f1（已accepted且权限允许自动执行），等待落地修正动作；完成后应调用evolution_complete登记'已完成+验证结论'（RULE-AI
- `MEM-20260818-44d52b4a` 2026-08-18 v3 :: 演进建议EVO-20260822-9fde48f1已accepted且权限允许自动执行，状态为executing，等待落地修正动作；完成后应调用evolution_complete登记'已完成+验证结论'（RULE-AI
- `MEM-20260825-aa9a969c` 2026-08-25 v1 :: 存在已 accepted 且权限允许自动执行的演进建议 EVO-20260822-3f483f1a（状态 executing），等待落地修正动作；完成后需调用 evolution_complete 登记'已完成+验证结论

## 簇#38 size=3 cos[max=0.9679 mean=0.9387] 主题≈fail-closed,fileservice,prepared/observed,原子写入
- `MEM-20260908-aaaa9225` 2026-09-08 v4 :: FileService 关键实现事实：factory.py:649 进程级单例，被 read/edit 工具及 SubAgent 共享；edit 全序列=锁→版本前置→基线字节复读→prepared 必须持久否则拒写（E
- `MEM-20260908-61371974` 2026-09-08 v1 :: FileService edit 完整防损坏序列：锁→版本前置→基线字节复读（防同尺寸同 mtime 第三方写）→prepared 必须持久否则拒写（EffectPreparedUnavailable，写前 fail-c
- `MEM-20260908-33ae7f75` 2026-09-08 v1 :: FileService.edit 防损坏序列（源码级核实）：锁→版本前置→基线字节复读→prepared 必须持久否则拒写（EffectPreparedUnavailable，写前 fail-closed）→原子替换→o

## 簇#39 size=3 cos[max=0.9637 mean=0.933] 主题≈merge后修复,修复排序,working_set红,working_set预存红
- `MEM-20260909-910dfea4` 2026-09-09 v1 :: 4 项 working_set 预存红的修复排在 merge 完成之后执行（用户决定，避免冲突解决期间测试噪音）；顺序为：先 merge 并修合并真回归、全量绿，后修 4 红，最后 push。
- `MEM-20260909-aa1fe581` 2026-09-09 v2 :: 用户决策（2026-09-09）：4 项 working_set 预存红修复放在 merge 完成之后进行，避免冲突解决期间测试噪音。4 红位于 tests/unit/test_tool_working_set_proj
- `MEM-20260909-03b4eea2` 2026-09-09 v3 :: 用户决定：4 项 working_set 预存红的修复放在 merge 完成之后执行（倾向 merge 后顺手修，避免冲突解决期间的测试噪音）

## 簇#40 size=3 cos[max=0.9621 mean=0.931] 主题≈mcp_dsh_write,execute_command heredoc,沙箱read-only,escalation
- `MEM-20260829-f704e84d` 2026-08-29 v6 :: MCP mcp_dsh_write 在工作区只读沙箱下会失败（file access denied under read-only mode）；可改用 execute_command heredoc 写工作区文件，或按沙
- `MEM-20260829-ce002153` 2026-08-29 v1 :: MCP 写入工具（mcp_dsh_write）在沙箱只读模式下会被拒绝；可改用 execute_command heredoc 在工作区写文件（mkdir -p + cat > file <<'EOF'），无需审批弹窗。
- `MEM-20260829-c704bc9e` 2026-08-29 v1 :: MCP 写文件工具（mcp_dsh_write）在沙箱只读模式下会被拒绝；写工作区文件可改用 execute_command heredoc（状态码 0），避免审批弹窗。

## 簇#41 size=3 cos[max=0.962 mean=0.9502] 主题≈integration r9,live-parity,-s ours merge,历史接通
- `MEM-20260817-b5992ff1` 2026-08-17 v14 :: 历史接通决策：用 -s ours merge（06414ed/f3acff0）把 lfl/main 并入 llm-first-loop main，定调以 integration R9 架构为准。虽名义丢弃 755 文件，
- `MEM-20260910-6fe94101` 2026-09-10 v5 :: 2026-09-09 历史接通决策：用 -s ours merge（06414ed/f3acff0）把 lfl/main 并入，定调以 integration R9 架构为准；merge 名义上丢弃 755 文件，但随后
- `MEM-20260911-fbd27048` 2026-09-11 v1 :: 2026-09-09 历史接通决策：用 `-s ours` merge（06414ed/f3acff0）把 lfl/main 并入，定调『以 integration R9 架构为准』。该 merge 名义上丢弃 755 

## 簇#42 size=3 cos[max=0.9603 mean=0.9338] 主题≈history_budget_chars,compact_ratio,experience-20260823-untitled.md,本地模型反复循环
- `MEM-20260823-38cdd2ac` 2026-08-23 v2 :: 经验文档 EXPERIENCE-20260823-untitled.md 已存在，主题为『本地模型压缩循环』参数侧解法：history_budget_chars=8000 过小导致高频压缩、失忆重试，建议调至 12000
- `MEM-20260823-f8871832` 2026-08-23 v4 :: 本地大模型反复循环的根因判定：history_budget_chars=8000 过小导致高频压缩失忆重试；参数对策为 budget 12000→30000、COMPACT_RATIO 0.95→0.85，需重启进程生效
- `MEM-20260823-68271629` 2026-08-23 v1 :: 本地大模型反复循环的根因之一：history_budget_chars=8000 过小导致高频上下文压缩、失忆重试；参数侧改进为预算 12000→30000、COMPACT_RATIO 0.95→0.85，需重启进程生效

## 簇#43 size=3 cos[max=0.956 mean=0.9418] 主题≈fastapi,ui/v2,vite,web端
- `MEM-20260903-ce839221` 2026-09-03 v1 :: llm-first-loop 镜像区 Web 端架构：前端 Vite+React+TS（webui/，base=/ui/v2/），构建产物 webui/dist 由 FastAPI（python -m llm_loop.
- `MEM-20260903-6ba980a1` 2026-09-03 v4 :: llm-first-loop-mirror 项目 Web 端架构：前端 Vite+React+TS（webui/，base="/ui/v2/"），构建产物 webui/dist 由 FastAPI 同源挂载；后端 pyt
- `MEM-20260903-45c35b0b` 2026-09-03 v1 :: llm-first-loop-mirror 项目 Web 端架构：前端 webui/（Vite + React + TS，vite.config.ts 中 base="/ui/v2/"，构建产物 webui/dist/）

## 簇#44 size=3 cos[max=0.9545 mean=0.9339] 主题≈lfl.continuity.remote,continuity,私有remote,ssh
- `MEM-20260907-47c7bdda` 2026-09-07 v3 :: LFL mirror 的 .git/config 含私有 continuity remote：lfl.continuity.remote=ssh://git@ssh.github.com:443/deyi2026/llm
- `MEM-20260908-a439326b` 2026-09-08 v1 :: LFL mirror 的 .git/config 配有私有远端 lfl.continuity.remote=ssh://git@ssh.github.com:443/deyi2026/llm-first-loop-con
- `MEM-20260908-667c0bad` 2026-09-08 v3 :: mirror 仓库 .git/config 中有 lfl.continuity.remote=ssh://git@ssh.github.com:443/deyi2026/llm-first-loop-continuity

## 簇#45 size=3 cos[max=0.9544 mean=0.944] 主题≈start-web-tunnel.sh,gen-cloudflared-config.sh,config.yaml,部署脚本
- `MEM-20260903-5036b455` 2026-09-03 v2 :: 已创建域名访问配套文件：cloudflared/config.yaml（named tunnel 配置模板，使用前需在 Cloudflare Zero Trust 创建 tunnel 并填入 Tunnel ID、下载 t
- `MEM-20260904-dab397bb` 2026-09-04 v1 :: 2026-09-04 创建 Cloudflare Tunnel 部署文件：cloudflared/config.yaml（named tunnel 配置模板，需手动填 Tunnel ID + credentials）、s
- `MEM-20260903-78577006` 2026-09-03 v3 :: 为域名访问创建了部署文件：cloudflared/config.yaml（Named Tunnel 配置模板，需手动填 Tunnel ID + credentials）、scripts/start-web-tunnel.

## 簇#46 size=3 cos[max=0.9518 mean=0.9342] 主题≈维护契约,ai_rules.lite.md,v15,development_repair_safety
- `MEM-20260817-de5f2e28` 2026-08-17 v21 :: docs/ai_rules.lite.md 当前 version=15（Agent/维护 playbook：development/repair safety + current-task authority + age
- `MEM-20260825-9d40e0fd` 2026-08-25 v4 :: docs/ai_rules.lite.md 为 Agent 维护 playbook，当前 version=15（2026-09-09，v15 新增 merge-absorb 处置）；约定：修改仓库行为（runtime/p
- `MEM-20260901-80ef46d2` 2026-09-01 v3 :: LFL 的 docs/ai_rules.lite.md 为 Agent/维护 playbook，当前 version=15（2026-09-09），v15 新增 merge 吸收处置条款；核心原则：development

## 簇#47 size=3 cos[max=0.9518 mean=0.9286] 主题≈按建议执行,用户授权,m1-g2 continuation,双跑方案
- `MEM-20260820-bdd93e13` 2026-08-20 v22 :: 用户 2026-09-15 指示'按你的建议执行'：授权按核验结论继续 M1-G2 干净 continuation——方案为各自干净 worktree（candidate 专用 + baseline 已有）+ 各自 ed
- `MEM-20260909-e0ba04d1` 2026-09-09 v4 :: 用户 2026-09-15 指令“按你的建议执行”：批准按 assistant 方案继续 M1-G2 干净 continuation（各自专用干净 worktree + 自建 venv 后再启动 baseline/can
- `MEM-20260915-8e1f409c` 2026-09-15 v1 :: 用户 2026-09-15 指示“按你的建议执行”：确认继续 M1-G2 干净 continuation 方案——按设计 v1.1 §12.1 M1 口径搭各自 venv 的 baseline/candidate 双跑环

## 簇#48 size=3 cos[max=0.9511 mean=0.9322] 主题≈lsof,进程存活验证,operation not permitted,ps被禁
- `MEM-20260910-eb0b3272` 2026-09-10 v2 :: 本镜像环境 ps 命令被禁用（Operation not permitted），ps 空输出曾导致进程不存在的误判；进程存活验证必须用 lsof（监听端口用 lsof -nP -i :8903，进程详情用 lsof -p
- `MEM-20260914-7b4d9f56` 2026-09-14 v1 :: 当前环境 `/bin/ps` 被禁用（Operation not permitted），会产生空输出并导致误判进程已死；进程存活验证必须改用 `lsof`：`lsof -nP -i :端口` 查端口监听、`lsof -p
- `MEM-20260914-0f935b5f` 2026-09-14 v1 :: 本环境 `ps` 命令被禁用（/bin/ps: Operation not permitted），曾因此误判进程已死；验证进程存活须改用 `lsof -p <PID>`（进程详情、cwd、打开的日志文件）与 `lsof 

## 簇#49 size=3 cos[max=0.95 mean=0.9199] 主题≈跨模型缓存,evo-20260820-0dbdf702,deepseek前缀,evo-20260820
- `MEM-20260824-8e8d80e4` 2026-08-24 v1 :: 待审演进建议 EVO-20260820-0dbdf702：验证'切换首轮全量 miss'是否被高估；DeepSeek 按字节前缀匹配，稳定前缀可能跨模型共享缓存键。
- `MEM-20260823-7cbb166b` 2026-08-23 v1 :: 存在两条待审演进建议：EVO-20260820-a637d2d7（cache_hit_show_in_answer=true 每轮注入缓存统计有固定 token 开销，建议降级为异常才提醒）；EVO-20260820-0
- `MEM-20260820-b07ac1c6` 2026-08-20 v1 :: 已提交演进建议 EVO-20260820-a637d2d7：cache_hit_show_in_answer=true 每轮注入缓存统计→固定 token 开销 + 诱导 AI 复述，建议降级为“异常才提醒”；及 EVO

## 簇#50 size=3 cos[max=0.9498 mean=0.9185] 主题≈定向修正,工具使用,最优路径,经验沉淀
- `MEM-20260811-fbaf291d` 2026-08-11 v12 :: 工具使用最优路径：先复用已验证最短工具路径，失败只做定向修正（参数错改参数，权限/开关错换路径，瞬态错误才重试）；连续同类失败即停止试错；发现更优用法或新参数约束立即沉淀经验。
- `MEM-20260816-3b6de885` 2026-08-16 v14 :: 工具使用最优路径：先复用已验证套路，失败只做定向修正（参数错改参数、权限/开关错换路径、瞬态错误才重试），连续同类失败即停止试错。
- `MEM-20260817-e05abab3` 2026-08-17 v1 :: 工具使用原则：先复用已验证最短工具路径，不重复探测；失败只做定向修正（参数错改参数、权限/开关错换路径、瞬态错误才重试），连续同类失败即停止试错；不确定时先 search_records/search_docs 查历史执

## 簇#51 size=3 cos[max=0.9467 mean=0.937] 主题≈lfl,llm-first core loop,agent runtime,harness
- `MEM-20260827-aa3752ca` 2026-08-27 v16 :: LFL（LLM-First Core Loop）项目：位于 ~/Project/llm-first-loop-mirror，v0.6.14，Apache-2.0，开源框架化（B 路线）进行中。自我定位为
- `MEM-20260824-595f8cf5` 2026-08-24 v28 :: 用户核心项目为 LFL（LLM-First Core Loop），本地路径 ~/Project/llm-first-loop-mirror，版本 0.6.14，Apache-2.0，开源框架化（B 路线
- `MEM-20260811-f17e578e` 2026-08-11 v53 :: 用户的项目 LFL（LLM-First Core Loop）版本 0.6.14，Apache-2.0 许可，状态为开源框架化（B 路线）进行中。自我定位：一个'AI 优先'（LLM-first）的 Agent 运行时（H

## 簇#52 size=3 cos[max=0.9466 mean=0.9369] 主题≈记忆待修正,搜索空结果,停止搜索,不伪造结果
- `MEM-20260823-60adece5` 2026-08-23 v2 :: 搜索类工具（search_archive/search_records）连续 2 次返回空结果时：以工具回执为准，目标不存在即停止该目标搜索，标注『记忆待修正』，如实说明并询问用户；不伪造结果，换参数重复搜同一目标不会产
- `MEM-20260824-e1c75386` 2026-08-24 v1 :: 搜索类工具（search_archive 等）连续空结果处理约定：以工具回执为准，目标不存在即停止该目标搜索，标注「记忆待修正」，如实说明并询问用户；不重复换参数搜同一目标（不伪造结果）。
- `MEM-20260825-e8eec2e8` 2026-08-25 v1 :: 搜索类工具（如 search_docs/search_records）连续 2 次空结果时，以工具回执为准：目标不存在即停止换参数搜同一目标，标注'记忆待修正'，如实说明并询问用户；确需继续请换全新目标或向用户求证。

## 簇#53 size=3 cos[max=0.9435 mean=0.9286] 主题≈b4bcd82,ff6297f,6a26259,22d766cf9
- `MEM-20260829-242d393b` 2026-08-29 v16 :: 2026-09-14 StateBraid P1 收尾三笔提交已落地核验属实：e2 仓 b4bcd82（三个回归测试从 bench/ 迁入 tests/ 供上游 CI 真正执行、statebraid 声明为可选 extr
- `MEM-20260903-0bf075a3` 2026-09-03 v3 :: e2 仓 `b4bcd82` 之后的 P1 已收尾内容：三个回归测试从 bench/ 迁入 tests/ 使上游 CI 真正执行；statebraid 声明为可选 extra（`pip install '.[stateb
- `MEM-20260914-d22c1931` 2026-09-14 v2 :: 2026-09-14 P1 收尾提交（已核验属实、工作树干净）：e2 仓 b4bcd82（三个回归测试从 bench/ 迁入 tests/ 使上游 CI unittest discover 真正执行、statebraid

## 簇#54 size=3 cos[max=0.9427 mean=0.925] 主题≈本地红,receipt,github全绿,base64编码
- `MEM-20260910-3761bade` 2026-09-10 v1 :: 未解决矛盾：用户指出 test_tool_working_set_projection.py 的 4 个失败测试在 GitHub CI 上全绿，但本地 4 failed；初步线索为 receipt 内容被 base64 
- `MEM-20260910-a48c1c5d` 2026-09-10 v1 :: 未决矛盾待查：用户指出 test_tool_working_set_projection.py 的 4 个测试在 GitHub CI 上全绿，但本地（纯净 HEAD 同样）4 failed；失败特征为 receipt 内
- `MEM-20260910-7b7faef9` 2026-09-10 v1 :: 未解疑点（2026-09-10）：用户称 working_set_projection 4 个测试在 GitHub CI 全绿，但本地重跑确认为 4 failed；失败特征为 receipt 内容全是 base64 填充

## 簇#55 size=3 cos[max=0.9317 mean=0.9246] 主题≈注入治理,结构他律,三层组合,injection-governance
- `MEM-20260811-72a26d17` 2026-08-11 v15 :: 当前活跃目标：注入治理专项（INJECTION-GOVERNANCE，id=GOAL-20260829-afd095ab）——根治注入块对弱模型的干扰，三层组合方案：L1 四层语义标记规范 / L2 注入预算硬上限+资料
- `MEM-20260830-8e597390` 2026-08-30 v2 :: 注入治理专项（GOAL-20260829-afd095ab）立项：根治注入块对弱模型干扰，从'标记自律'转向'结构他律'三层组合（L1 四层语义标记规范/L2 注入预算硬上限+资料按需化+身份剥离+程序恢复边界/L3 弱
- `MEM-20260830-36f205e3` 2026-08-30 v1 :: 注入治理专项（INJECTION-GOVERNANCE）状态 active：目标 GOAL-20260829-afd095ab，核心原则『结构他律 > 标记自律』，三层组合（L1 四层语义标记规范/L2 注入预算硬上限+

## 簇#56 size=3 cos[max=0.9295 mean=0.9233] 主题≈anchor_sess,认知运行时,解耦,session对象
- `MEM-20260828-102c2eeb` 2026-08-28 v1 :: CR-R1.1 修复约定：认知运行时会话身份与任务锚点解耦——engine._focus.anchor_sess 是 Session 对象（build_task_anchor 专用），Cognitive 路径一律使用 s
- `MEM-20260828-e41ca4f8` 2026-08-28 v7 :: 关键陷阱：engine._focus.anchor_sess 是 Session 对象（build_task_anchor 专用），不是 session_id 字符串。Cognitive 路径（StateStore/Re
- `MEM-20260828-1237e922` 2026-08-28 v1 :: engine._focus.anchor_sess 是 Session 对象（build_task_anchor 专用）而非 session_id 字符串；传给 GoalStore.get(prefer_session_

## 簇#57 size=3 cos[max=0.9293 mean=0.9275] 主题≈hermes,browser_exec,code-as-action,浏览器agent
- `MEM-20260810-8be6054a` 2026-08-10 v70 :: Hermes 浏览器方案调研结论：用单个 browser_exec(code) 取代多个 browser_* 逐动作工具，模型写 Python 在 browser-use CLI 守护进程执行，预置 helper，页面转
- `MEM-20260810-435dcca3` 2026-08-10 v16 :: Hermes 浏览器方案研究结论：用单个 browser_exec(code) 工具（底层 Browser Use CLI 3.0，CDP 驱动浏览器，预置 helper，页面用无障碍树转文本）替代多个 browser_
- `MEM-20260816-b92a4a6e` 2026-08-16 v1 :: Hermes Agent（Nous Research）浏览器方案：将传统的多个细粒度浏览器工具（browser_click/type/snapshot 等）替换为单个 browser_exec(code) 工具（code

## 簇#58 size=3 cos[max=0.9278 mean=0.9121] 主题≈schedule,检查点,唤醒机制,后台任务
- `MEM-20260821-460ac138` 2026-08-21 v1 :: schedule 检查点唤醒机制：到点后必须把任务完成信号（如基准完成）作为信息注入会话才会唤醒大模型继续处理，仅注册提醒会停在等待。
- `MEM-20260821-d77cdd86` 2026-08-21 v1 :: schedule 到点后必须把'测试完成'信息真正注入会话才会唤醒大模型处理，否则停在等待（用户明确提示）；注册检查点时应把要执行的取数+分析指令写入提醒内容
- `MEM-20260821-831386d5` 2026-08-21 v1 :: schedule 提醒到点后，必须把"测试完成"等承载结果的信息真正注入会话（经协调通道）大模型才会被唤醒处理，否则会停在等待。

## 簇#59 size=3 cos[max=0.9269 mean=0.9178] 主题≈cache_hit_show_in_answer,p0-1,config.py:269,evo-a637d2d7
- `MEM-20260810-8ede3707` 2026-08-10 v57 :: 实施缓存命中率治理 P0-1 时发现 config.py:269 的 cache_hit_show_in_answer 已是 False 且带 EVO-a637d2d7 注释，与方案描述「当前 True」不一致——疑似该
- `MEM-20260819-51c06637` 2026-08-19 v7 :: 缓存命中率治理（FINAL-EXECUTION-PLAN-cache-hit-governance.md）：config.py 的 cache_hit_show_in_answer 默认值 True→False（常态注入
- `MEM-20260820-6781ff1d` 2026-08-20 v3 :: 实施 P0-1 时发现 config.py:269（src/llm_loop/config.py）的 cache_hit_show_in_answer 已是 False 且带 EVO-a637d2d7 注释，与方案描述的

## 簇#60 size=3 cos[max=0.9254 mean=0.9133] 主题≈tool_tail,typeerror,3f09ffc,bd203b5
- `MEM-20260819-c9c8f5bc` 2026-08-19 v6 :: 2026-08-20 回滚排查闭环：崩溃根因=93ac99e(回滚点前)给 build.py 加 tool_tail 传参，history.py 参数支持在 9f157b5(回滚点后)——bd203b5 提交态内部不一致
- `MEM-20260819-e84aa5e2` 2026-08-19 v1 :: 回滚到 bd203b5 并重启后发生崩溃：bd203b5 提交内部不一致——build.py 向 build_history_messages() 传 tool_tail= 参数（93ac99e 引入），但该函数不接受此
- `MEM-20260819-273e08f9` 2026-08-19 v1 :: 崩溃根因：bd203b5 代码内部不一致——build.py 调用 build_history_messages() 时传 tool_tail= 参数（93ac99e 引入），但 bd203b5 的 history.py
