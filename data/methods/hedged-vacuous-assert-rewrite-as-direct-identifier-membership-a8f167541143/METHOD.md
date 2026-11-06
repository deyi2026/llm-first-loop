---
method_id: hedged-vacuous-assert-rewrite-as-direct-identifier-membership-a8f167541143
name: hedged-vacuous-assert-rewrite-as-direct-identifier-membership
description: 给行为改动补测试时，排除型断言若被 `or True`/布尔常数折迭中和成恒真式（写时多半是对消息格式没把握而加的"保险"），它对回归零保护，还会把"应拦反例"撑成假覆盖。判别事实在写时即可见：拟检查对象的确切标识符（如 helper 返回的 task_id/具名字段）已在本次编辑上下文内，直接成员断言（tid not in msg）即可表达该未知量且不依赖消息排版。落测试后机械扫新增 assert：答不出"什么输入会让它红"的断言当场重写。
aliases: 测试断言 or True 永真, assert 永远不会红 怎么改, not in 直接判成员 别切字符串位置, 假覆盖 应拦反例全绿, 断言里加保险让它必过
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a6989bff-e814-43eb-9f8a-a24f42790dd9:1269:0f5508999f23ba4984e4
evidence_refs: learning:learn:ad42830d828d
created_at: 2026-11-06T08:40:26.374627+08:00
updated_at: 2026-11-06T08:40:26.374627+08:00
---
## Trigger
为改动新增/修改测试断言，尤其是『某标识符不得/必须出现在生成的拒绝消息里』这类排除型断言；或写 assert 时发现自己在表达式尾部加了 or True、and True、注释掉左操作数等让断言必然通过的缓和结构。

## Discriminator
两个写时已知事实足以判死/改写：1) 拟断言对象的确切标识符已在本次编辑内拿到（建任务 helper 的返回值就是 task_id，无需从消息里反推位置）；2) assert 表达式出现布尔常数折迭（or True 等）在语法上恒真——写入回执的 diff 里该行可见即定论，与后续测试全绿与否无关。

## Short path
- 写每条新 assert 前先用一句话说出它锁定的未知量（如『cancelled 任务不得进 G3 拦单』）
- 用已知确切标识符写直接成员断言（assert cancelled_tid not in result.content），不做消息位置切片
- 落编辑后扫一遍新增 assert：发现 or True / and True / assert True 等常数即视为该断言未写，当场重写为直接检查
- 跑测试确认正例绿，再确认应拦反例用例在断言意义上真能红（最稳：在改动前实现上跑一次）

## Stop conditions
- 每条新增 assert 都能答出『什么输入会让它红』
- 应拦反例用例全部真实存在，且其通过不是被恒真断言撑起来的

## Verification
- 逐条反问新增 assert 的失败输入；答不出=恒真断言，改写
- 把应拦反例测试在改动前的实现上跑一遍，确认对应断言会失败（防假覆盖）

## Counterexamples
- 断言语义本就是位置/结构化的（如『该段前 40 字符不得含某前缀』）且不含常数折迭时，切片断言合法，不必强改成成员检查
- 显式标记跳过的用例（skipif/xfail）不属于恒真断言
- 存量恒真断言位于本次未触碰的文件：按棘轮口径不顺手重写，只清触碰文件
