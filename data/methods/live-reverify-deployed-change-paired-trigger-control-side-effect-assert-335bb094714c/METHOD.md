---
method_id: live-reverify-deployed-change-paired-trigger-control-side-effect-assert-335bb094714c
name: live-reverify-deployed-change-paired-trigger-control-side-effect-assert
description: 部署后对具名行为变更（命名错误码、绑定/降级标注）做 live 复验的验收设计：先核部署身份（待验提交 ancestry in-deployed、generation 匹配），确保探针命中的是已部署代而非旧代码；每个具名行为配一对样例——触发例送越界输入读回命名 reason，对照例选该行为必须不触发的表面证明不误报；拒绝后独立断言目标元素无残留写入；会污染真实用户表面的正边界测试跳过 live，收口明列未验证并引源码常量为真值。与一般能力审计（逐动作最小实测）区分：这里是验收已部署的具名变更，核心是配对设计与部署代对齐。
aliases: 部署后复验怎么做, 上线后验证新错误码生效, 复验别测到旧版本代码, 怎么证明降级标注不误报, 被拒后确认页面没残留输入
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:c2df336a-eb98-4baa-9220-9e80d36e4ee2:310:7c4e424d40da43e33f8c
evidence_refs: learning:learn:80450e28b29e
created_at: 2026-10-31T15:10:35.991209+08:00
updated_at: 2026-10-31T15:10:35.991209+08:00
---
## Trigger
交接文档或任务图要求对已部署版本做 live 复验，且验收对象是具名行为变更（如命名错误码、title_relaxed 之类绑定/降级标注），环境中同时存在：可触发的越界路径、一个该行为不应触发的对照表面、仓内可检索到的真值常量。

## Discriminator
任务名已具名待验行为 + 一次精确标识符检索即可定位常量与拒绝层（实现与测试同时命中）+ 部署回执给出 in-deployed/ancestry 与 generation 匹配 + bound 页面/桌面 status 显示可用表面——四者齐备时，验证方案收敛为『触发例+对照例+副作用断言』的确定组合，不需要再枚举其他验证面或重新推导实现链。

## Short path
- 核部署身份：待验提交逐个 git ancestry in-deployed + generation 匹配；不满足则停止 live 复验，先解决部署
- 一次精确标识符检索定位真值源：上限常量值 + 两层拒绝点（契约层/adapter），作为回执逐字对照基准
- 触发例：送越界输入，读回命名 reason 串，与源码命名枚举逐字比对
- 对照例：选该行为必须不触发的表面（如 CG/AX 标题一致的窗口→exact 绑定、degraded 为空），证明标注不误报
- 副作用断言：拒绝后 hydrate 目标元素确认无残留写入，用同页正常元素作『应有值』形态对照
- 会污染真实用户表面的正边界（恰好等于上限的接受侧）跳过 live，收口明列未验证项并引源码常量为真值

## Stop conditions
- 每个具名行为已拿到三件证据：部署代内的触发回执（含命名 reason/标注值）+ 对照面不触发回执 + 拒绝后副作用断言，即停止扩大验证面
- 触发或正边界动作会在真实用户/生产表面留下难清理痕迹时停手，改引源码常量与单测并标注未验证
- ancestry 显示待验提交未 in-deployed 时停止复验——探针验到的是旧代码

## Verification
- 待验提交均被 git merge-base --is-ancestor 判为部署 HEAD 祖先，且 generation 匹配
- 回执中的 reason/标注值与源码常量或命名枚举逐字一致
- 对照面返回非触发形态（如 binding=title_exact、degraded=[]）
- 拒绝后目标元素状态与动作前一致，同页正常元素可取到值作对照

## Counterexamples
- 一般能力审计（问『这套能力完善吗』，无具名行为变更与部署代约束）：按逐动作最小实测+状态断言即可，配对设计属过度工程
- 找不到『必须不触发』的对照表面：只能报触发例结果并明标对照缺失，不得宣称不误报
- 行为变更尚未部署：探针验的是旧代码，先等部署或换环境，不做复验
- 触发例需向共享/生产数据写入不可清理状态：放弃 live 触发，以源码+测试为真值收口
