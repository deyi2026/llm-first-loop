---
method_id: replay-minimal-failing-repro-before-environment-recheck-0b5dae3dee4f
name: replay-minimal-failing-repro-before-environment-recheck
description: 修复已部署并重启成功后，若修复前存在参数完全确定、失败观测已记录的最小复现查询/断言，验证的第一步应是原样重放该复现，而不是先做环境预检（目录枚举、全量读源码、全页基线快照）再人工扫描证据找目标对象。复现结果中的身份字段（如对象 name）可同轮确认打到了正确页面/目标，环境检查只作为结果报错或歧义时的条件回退，一次只验证一个假设。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:1606:849104ca8a3294566c5d
evidence_refs: learning:learn:1803d4c1628c
created_at: 2026-09-18T06:32:38.386872+00:00
updated_at: 2026-09-18T06:32:38.386872+00:00
---
## Trigger
一次修复刚部署/重启且回执 status=succeeded，当前目标是确认 bug 是否修复，且修复前已有一个机器可复查现：查询参数精确、失败时的观测值已知、修复后的期望值明确。

## Discriminator
当时已存在两个事实即可唯一化验证动作：(1) 修复前该精确查询的失败观测（如 filtered projection matched_total=0，而目标对象 name 已知存在于页面）；(2) 重启回执确认新版本已生效。二者合起来，验证动作就是重放同一查询并断言字段变化，无需先确认更广的环境事实。

## Short path
- 读部署/重启回执，确认 status=succeeded 且指向新构建（未知量：新版本是否已生效）
- 原样重放修复前的最小失败查询到新 runtime（未知量：bug 是否仍复现），不先做目录枚举/全量源码阅读/全页快照
- 断言具体字段按修复预期变化（如 matched_total 0→1、kind generic→heading），并利用结果内身份字段（name=ProbeTitle）同轮确认命中正确页面，替代独立的环境确认
- 仅当查询报错或结果歧义（0 匹配无法区分修复失败与页面错误）时，才做一次廉价环境检查（进程/端口），逐个假设排查
- 修复验证通过后，再对相邻写路径做回归冒烟（click/fill），各自用精确投影取 grounding ref，关键断言通过即闭环

## Stop conditions
- 复现查询返回修复后预期值，且结果中身份字段证明命中的就是原 bug 目标 → 修复已验证，停止任何进一步的环境再确认
- 查询失败或结果歧义 → 切换到环境假设，每次只验证一个假设，不做宽枚举
- 范围内回归冒烟的关键副作用断言（点击计数、写入值）通过 → 本轮验证结束，不再追加观测

## Verification
- 重放结果与修复前记录的失败观测形成直接对照（0→1、generic→heading），且差异正对应所修根因（如 DOM/AX kind 合并遮蔽）
- 结果来自重启后的 runtime generation（结果内 scope_facts/回执 generation 与部署回执一致），排除打到旧实例
- 结果包含目标身份证据（对象 name/aria-label）而非仅计数，排除查询命中错误页面造成的假阳性

## Counterexamples
- 复现查询的失败模式本身歧义（0 匹配既可能是修复失败也可能是环境错）且每次重放成本高时，先做一次廉价存活检查（单条 pgrep/curl）是合理前置
- 没有精确复现、bug 只有定性描述时，必须先构造可判别的观测，直接发任意查询并不优于探索
- 部署回执未确认成功、或无法确认查询路由到的服务版本时，必须先做版本/路由核验，否则复现结果不可信
- 修复可能影响相邻行为时，仅重放原复现不足以宣告无回归，仍需相邻路径冒烟（本例的 click/fill 即属此范畴，不能省）
