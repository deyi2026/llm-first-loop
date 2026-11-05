---
method_id: graded-proof-and-pin-for-guard-removal-by-compensating-control-aa39265f32a4
name: graded-proof-and-pin-for-guard-removal-by-compensating-control
description: 当修复=删除本层守卫（如 handler 内鉴权），安全性完全依赖另一层已有控制（如装配层挂载的共享 guard）时，『控制代码存在+现有测试通过』不构成验证：现有测试若自建最小挂载，对该控制零覆盖。提交前需递进补证：实证替代控制的每请求语义（开启策略下正证放行并前置断言排除假阳性、反证非豁免来源仍被拦）、用真实装配路径端到端测两方向、结构固定挂载串（有 guard 挂载、无裸挂载，改回即红），并把控制的挂载文件纳入补丁与审查范围。本 episode 因缺这些证据经历 4 轮 REVISE 才凑齐。
aliases: 删掉 handler 二次鉴权后怎么证明还有一道闸, 靠 include_router 统一鉴权时审查要什么证据, 测试挂载没带 dependencies 算不算覆盖, 防裸挂载回退的钉子测试, 删守卫后补偿控制实证
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:d0e6ba0c-dfdb-4a7e-b110-850f0ae238a6:836:d023a4e89400cb4506a9
evidence_refs: learning:learn:25133e10e32c
created_at: 2026-11-05T12:47:15.834965+08:00
updated_at: 2026-11-05T12:47:15.834965+08:00
---
## Trigger
修复手段是删除某层守卫检查，其安全性论证依赖另一层（装配/上游/共享挂载点）已有的等价控制；且改动已通过现有回归与 lint，正准备提交送审。

## Discriminator
两条提交前就可见的事实：① 替代控制位于装配层（挂载行带 dependencies=[Depends(guard)]），不在本文件；② 现有测试对该路由无任何鉴权断言，且测试用自建最小 app 挂载、不经过装配层。二者合并 ⇒ 现有测试对替代控制零覆盖，『测试通过』不能作为删守卫的证据。

## Short path
- 读守卫定义与真实挂载点，确认替代控制的每请求语义（含豁免口径）与被删守卫语义的差异，锁定根因；若语义不等价，先修分歧而非删守卫
- 读现有测试的挂载方式与鉴权断言：自建最小挂载且无鉴权断言 ⇒ 判定现有测试对控制层零覆盖
- 删除守卫后、宣布验证通过前先补实证：开启策略下正证豁免放行（前置断言 env 级判定为 True，排除『策略本来就关』的假阳性），反证非豁免来源仍被拦截
- 用真实装配路径（如 ASGITransport 打真 app）端到端验证放行与拦截两个方向
- 结构固定：断言挂载文件存在带 guard 的挂载串、且无该 router 的裸挂载，使回退会变红
- 把控制的挂载文件并入补丁与审查范围（或收窄声明范围与实际 delta 一致），一轮送审同时覆盖 delta 与控制

## Stop conditions
- 正反双向实证 + 真实装配端到端 + 结构固定测试齐备，且审查/补丁范围同时包含 delta 与控制的挂载文件
- 若发现替代控制与被删守卫语义不等价（如豁免口径不同），停止删除路线，先修语义

## Verification
- 反转检查：临时移除挂载层 guard（模拟裸挂载），测试套件必须变红
- 策略开启的前置断言（env 级判定为 True）确保正证不是策略关闭造成的假阳性
- 补丁声明的 scope 与实际提交的文件集合一致，控制所在文件在审

## Counterexamples
- 修复是新增守卫而非删除，不存在替代控制问题，常规行为测试即可
- 现有测试本就用真实 app 组装、控制层已被覆盖——只需 delta 测试，无需全套结构固定
- 被删检查是同层死代码或重复路径，剩余同层检查已被现有测试覆盖
- 无门禁/审查要求的非安全重构，按此全套升级属过度验证
