---
method_id: attribute-ambiguous-suite-failures-by-baseline-reproduction-54821773bd1f
name: attribute-ambiguous-suite-failures-by-baseline-reproduction
description: 门禁/全量验证回执出现失败集合且归属未知时，不读 traceback 文本推断相关性、不顺手修：用回执中已有的变更前基线 commit 身份开独立 worktree，同机同环境只复现失败子集。基线上同样失败=既有问题，再 unset 疑似宿主开关二分：仍红=基线漂移（登记 known-failures），转绿=env 继承、结论不可移植；基线通过=本次回归必须先修。每条失败有复现证据才可宣称『与本次改动无关』。why_shorter：把 N 个失败 × M 种成因缩成一个对照实验。
aliases: 全量测试红了怎么判断是不是我改出来的, pre-existing 失败快速排除, 先在旧提交上复现失败再动手, 测试失败先归因再修, 宿主环境变量把测试搞红了怎么查, known failures 基线怎么定
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:6160:ea07ec1e9ebd21f350b2
evidence_refs: learning:learn:6724e332cb25
created_at: 2026-11-02T09:38:34.959453+08:00
updated_at: 2026-11-02T09:38:34.959453+08:00
---
## Trigger
长生命线仓库的门禁/全量测试回执出现非空失败集合，且当时已同时掌握：（a）失败测试具名清单、（b）变更前基线提交身份（上一部署 git_head 或上轮提交）、（c）本次改动文件清单；闸门或用户需要知道失败是否由本次改动引入

## Discriminator
失败清单 + 基线 git_head + 改动文件清单三者已在手，即可把『是我的吗』缩成『在基线 worktree 上跑同一失败子集』的二分实验；同机同环境执行以排除环境差异干扰

## Short path
- 从全量回执提取失败测试清单；未知量：这些失败是本次 delta 引入的吗？
- 用已知变更前 git_head 开独立 worktree（不动工作区），只跑该失败子集；未知量：基线上是否同样失败？
- 同样失败 ⇒ 既有问题；在基线上 unset 疑似宿主开关（如 LFL_* 类变量）重跑，区分『真实基线漂移（登记）』与『宿主 env 继承（结论不可移植）』
- 基线通过 ⇒ 本次回归，先修复并重跑该子集，再继续交付
- 每条失败有带证据的归类即停；不把对无关失败的修复混入本次提交

## Stop conditions
- 每个失败都有可复现证据支撑的归类：回归已修／基线漂移已登记／环境继承已记录开关名
- 闸门要求零失败且不接受 known-failures 注记时，停止归因路线，转修复或正式豁免流程

## Verification
- 既有失败在基线 worktree 上逐条重现，与宣称的归因一致；回归类在修复后消失
- 环境类失败在清掉宿主变量后行为与 CI 口径一致
- 新加回归测试在基线上按预期失败（红灯实验），证明测试真的设防而非碰巧通过

## Counterexamples
- 套件很小、全量重跑很便宜时，直接在基线整体重跑即可，无需分子集
- flaky/时序型失败单次复现不足，需重复运行；worktree 间端口或资源竞争会制造假差异
- 失败由未提交/未跟踪的工作区状态引起时，干净基线 worktree 上不复现，会被误判为回归，需先核对 git status 完整清单
- 闸门规则是『零失败才放行』且不认基线注记时，归因本身不解锁，只能修或走定点豁免
