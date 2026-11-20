---
method_id: audit-pin-set-vs-execution-closure-difference-4d43e47bd218
name: audit-pin-set-vs-execution-closure-difference
description: 审查以固定文件集合哈希/白名单实现『受控方不可自证』的门禁或供应链校验时，关键未知量不是白名单逻辑本身对不对，而是『被pin入口实际执行到的文件闭包』与『被pin集合』的差集：从被pin入口（workflow 的 run:/uses:、入口脚本的 import/subprocess）机械提取执行边，凡被执行却未被pin的仓库内文件，都是受控方改内容即可转绿、且不触发任何哈希对照的旁路面。对每个差集项构造『恒绿且pin哈希不变』的最小对手输入来定级并给修复方向。
aliases: pin了配置没pin脚本怎么审, 白名单漏掉实际执行的文件, 改脚本恒绿骗过哈希门禁, run行引用未纳入固定集合, 门禁自证旁路排查, supply-chain pin覆盖面检查
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:d3eac4ce-a161-4461-9f11-2f18e8228b8f:0:2ae4af56fee2160ea23d
evidence_refs: learning:learn:8afe3e4e8ba2
created_at: 2026-11-17T00:32:36.515630+08:00
updated_at: 2026-11-17T00:32:36.515630+08:00
---
## Trigger
审查对象用 pin/哈希对照固定一个封闭文件集（gate blob、allowlist、checksum manifest）来阻止受控方（候选PR作者、下游内容生产者）自证通过，且被pin的入口配置自身会执行或加载仓库内其他文件；或攻击清单中出现『受控方改门禁文件假绿』类条目。

## Discriminator
被pin入口配置里的显式引用边（run:/uses:/import/子进程命令行）逐条指向的仓库内路径，是否全部出现在 pin 集合字面量中——差集非空即当场可写证据，不需要运行代码，也不依赖对外部API语义的猜测。

## Short path
- 读pin集合定义，抄出被固定路径的字面量清单
- 只读提取被pin入口的全部执行引用边（run:/uses:/import/subprocess），构成执行闭包
- 计算闭包减pin集合的差集；为空则此防线闭合，转向其他攻击面（如同名实体碰撞、外部语义未在代码内固定）
- 对每个差集文件构造最小对手输入：改成恒绿/恒过，且不触碰任何被pin路径
- 按下游决策对该pin的信任强度定级（直接放行合并/发布则为高危），修复方向为把差集文件纳入pin集合或对主线做blob对照
- 为至少一条差集攻击补反例测试：改动差集文件必须被HOLD，且拒绝理由不得归类为『不可用/可重试』

## Stop conditions
- 执行闭包 ⊆ pin 集合，或差集全部落在受控方不可写的范围（如仓库外按tag/digest固定的第三方组件）
- 差集文件不在通过判定路径上，其结果不进入门禁结论
- 绑定粒度是整commit/整树哈希而非文件级白名单，任何内容修改都使绑定失效

## Verification
- 对手输入必须同时满足：门禁结论翻绿、所有被pin blob的哈希逐字节不变
- 确认差集文件的改动确实在受控方可提交范围（含新增入口文件本身不在pin集合的情形）
- 用只读仓库事实固定每个差集项的证据（引用边行号 + pin清单行号），不靠单测通过替代

## Counterexamples
- 入口只执行仓库外、按tag/digest固定的官方action，仓库内容差集为空——防线闭合，不应硬套此法
- 未被pin的脚本属于非必需job或只做analytics，输出不进入门禁判定——差集项无威胁
- 机制为commit级整树CAS：改任何文件都使绑定失效，文件级差集分析不适用
- 受控方对仓库内容无写权限的纯外部审计场景，自证攻击前提不存在
