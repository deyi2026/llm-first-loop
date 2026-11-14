---
method_id: sweep-sibling-enumeration-sites-when-adding-new-variant-c78076617540
name: sweep-sibling-enumeration-sites-when-adding-new-variant
description: 在门禁靠硬编码兄弟标识集合（profile 字面量集、复合 is None 计划判据、工具 allowlist）做成员判定的系统里新增变体时，反例/审查通常只点名一个漏注册点，但同类漏注册是多点系统性的：成员不在集合即直接 return（fail-open 放行），或条件少一个变量即先走错 fallback。做法：用反例点名符号+兄弟标识（旧字面量/旧变量名）一次全仓 grep 列全所有成员判定/选择/fallback 站点并逐点分类；逐点最小修复；把反例逐字复现为走真实绑定路径的负测（断言具体拒绝码、send scope 不打开），fallback 类把误走的生产者 monkeypatch 成硬断言哨兵证明零回落；分层回归收尾。deny-by-default 门禁与注册表驱动分发不适用。
aliases: 新profile没进门禁集合怎么排查, 硬编码allowlist漏了新成员, 条件判断少写了新plan变量, 加新变体前先扫兄弟标识出现点, 放行门禁逐点补齐再回归
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:1958:923398baf1155420965a
evidence_refs: learning:learn:0d79d92556da
created_at: 2026-11-14T01:33:53.330382+08:00
updated_at: 2026-11-14T01:33:53.330382+08:00
---
## Trigger
在以硬编码成员枚举实施门禁/选择/fallback 的系统里接入新变体（新 profile、新 plan 类型、新工具类）；或收到反例/审查指出新变体在某处被漏注册——未校验即被放行进入敏感 scope，或生命周期条件漏变量导致先走了错误 fallback。

## Discriminator
门禁实现呈『成员不在兄弟字面量/变量枚举集合 ⇒ 直接 return 或走宽松分支』的形状，即未知成员 fail-open 而非报错；或同一检索输出里兄弟判据基数不一致（部分行已含全部兄弟变量、个别行少一个）——这两类信号在动手前的 grep/直读输出里即可见，证明漏注册是多点系统性问题，不止反例点名的那一处。

## Short path
- 一次全仓 grep 同时用两个键：反例点名符号 + 兄弟标识（旧 profile 字面量、旧 plan 变量名），列出全部成员判定/选择/fallback 站点，逐站点分类必改/无关
- 每个漏注册站点做最小修复：集合补字面量（必要时以字面量代替 import 防循环依赖）、复合条件补变量；不重构门禁本身
- 把反例逐字复现为负测，走真实绑定路径（真实 Execution bind → checked attempt），断言具体拒绝码且敏感 scope 不再打开；禁止只断言配置/模型字段正确
- fallback 类修复：把被误走的 fallback 生产者 monkeypatch 成硬断言哨兵，用真实运行引擎路径证明哨兵零触发且新路径真实落账
- 分层回归：新专项 → 旧专项 → 关键词选择器 → 综合套件，全绿后收尾

## Stop conditions
- 所有枚举站点均已确认包含新变体或显式豁免并以注释锁定；负测红→绿、哨兵零触发、分层回归全绿
- 门禁为 deny-by-default 且错误码已点名唯一注册点时，修复该点即可，免做全仓站点扫描

## Verification
- 负测先于修复运行必须复现出反例（红），修复后转绿
- grep 兄弟字面量/变量名复查：不存在仍缺新变体的成员判定点
- 哨兵断言：真实运行路径上 fallback 生产者从未被调用

## Counterexamples
- 门禁是 deny-by-default：未知成员直接抛错并点名注册位置，漏注册会大声失败，修点名处即可，不需要站点扫描
- 变体经单一注册表/数据驱动配置分发，各门禁查询注册表而非各自硬编码集合：只需注册一处
- 新变体语义上不应继承该门禁（有独立更严门禁或严格度不同）：盲目加入集合会制造错误耦合，须先确认继承语义正确
- 纯新增代码路径、没有既有兄弟枚举可参照：无从也无需做兄弟站点扫描
