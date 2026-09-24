---
method_id: mine-read-source-conventions-before-writing-derived-artifacts-e9d2fc4d0154
name: mine-read-source-conventions-before-writing-derived-artifacts
description: 在编写派生自生产代码的模板/prompt/脚本前，先把本 episode 已读源码中显式记录的格式约定与防御机制提取为派生物的规格。本 episode：解析纯函数源码早已注明'模板需双大括号转义（.format 渲染）+ 带双大括号纠错分支'，实验脚本却把单大括号 JSON 示例交给 .format()，导致 6/9 组渲染报错；重跑又因多次同步真实 LLM 调用超命令时限被杀且未落盘，靠后台执行+增量落盘才闭合。若先沿已读约定写脚本并对批量调用预估总时长，一次运行即可取得全部对照组数据。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5e09cedf-9412-454e-b7a9-f0247530ef7c:20:ea56c22ba490f49921c7
evidence_refs: learning:learn:e60cb397490d
created_at: 2026-09-22T17:16:30.647171+00:00
updated_at: 2026-09-22T17:16:30.647171+00:00
---
## Trigger
需要编写与既有生产 artifact 同构、或复用其渲染/解析机制的派生物（prompt 模板、实验脚本、配置），且该机制的源码（含注释与防御分支）在本 episode 已被读取

## Discriminator
已读源码中存在显式记录的格式约定或防御机制——如注释说明模板经 .format() 渲染必须 {{}} 转义、解析器带双大括号纠错分支。这一事实把'派生模板里 JSON 示例怎么写'从多种写法缩到'转义大括号或改用拼接渲染'一两个选项，且在写脚本之前就已可见

## Short path
- 列出派生物将复用的渲染/解析机制（如 .format() 渲染含 JSON 示例的模板、json.loads 解析产物），明确未知量：我的副本要满足哪些格式约束
- 从已读源码提取该机制的约束清单：转义约定、注释里记录的已知失败模式、防御性纠错分支——源码本身就是副本的规格
- 按规格写派生脚本，不引入源码已防过的同类错误（单大括号 JSON 交给 .format 之类）
- 对批量真实 LLM 调用先估算总时长，可能超过命令时限则直接后台执行，且每次调用后增量落盘
- 一次运行取得全部对照组结果，经生产解析链路验证组间差异可唯一归因于设计变量后停止

## Stop conditions
- 基线组复现已知问题、实验组产生可判读对照数据，且组间差异无脚本自身错误混杂
- 派生模板渲染产物可被生产解析函数原样解析（如 JSON 示例无占位符冲突）
- 实验产物全部落在隔离目录/临时目录，未触碰生产数据

## Verification
- dry-run 渲染派生模板，确认无占位符冲突、JSON 示例可被 json.loads 解析后再发起真实调用
- 对照组除设计变量外其他条件完全一致（同历史、同模型、同温度）
- 核对落盘记录覆盖全部计划 run，无因超时丢失的组

## Counterexamples
- 派生脚本不复用生产渲染机制（f-string/字符串拼接直接构造），转义约束不适用，无需先挖约定
- 实验目的就是测试该失败模式本身（如验证双大括号自动纠错），必须故意构造畸形变体，套用约束会毁掉实验
- 真实运行时 schema 与已读源码默认不一致（源码非权威规格），需以运行时探测为准而非源码注释
