---
method_id: mandate-anchored-enforcement-audit-before-gating-660a179d6684
name: mandate-anchored-enforcement-audit-before-gating
description: 治理类任务（给一类终局/裁决写入口加程序级硬门）执行前：先从任务/演进记录提取三要素——违规类别、要求的拒绝形态、受影响入口名；优先解决显式指令要求的核实未知量（如回执声明会话不自动收到、须查状态源确认 executing），再做任何探索式搜索；用入口名做内容搜索一步定位 registry 与 handler，而非文件名通配枚举；逐入口在 handler 及其 import 的 runtime 模块 grep 强制关键字（evidence 等），分类现状：无强制/opt-in/强制；只对缺口入口实现门，并复用兄弟入口已有的强制习语（既有 verifier、fail-closed、BLOCKED+reason_code+逃生出口）；TDD+全量回归后用状态工具点名的完成能力登记。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:536:688f618708c1f752640c
evidence_refs: learning:learn:6384ac739e93
created_at: 2026-09-23T23:52:58.534714+00:00
updated_at: 2026-09-23T23:52:58.534714+00:00
---
## Trigger
任务/演进/权威映射记录要求对一类写入口（如终局状态写入）增加程序级硬拒绝，且记录已点名违规类别与受影响机制或入口名；或回执/指令显式要求先核实某状态再继续执行。

## Discriminator
记录中是否已存在可直接锚定的具体名称：入口名（如 update_goal/task_update/service_control）与强制语义关键字（evidence/evidence_level/evidence_refs）。存在即表明定位代码可用内容搜索一次命中、现状审计可用关键字 grep 分类，无需文件名枚举或整文件通读。注意：schema/docstring 命中不等于消费，需追到真实写路径。

## Short path
- 读全任务/演进记录，提取三要素：违规类别、要求的拒绝形态（工具入口 BLOCKED）、受影响入口名。
- 先完成显式指令的核实未知量：查 pending_actions/状态源确认演进确为 executing（回执声明本操作不会自动送达会话）。
- 用入口名做内容搜索，一步定位 registry 与 handler 文件；跳过文件名通配枚举（已出现一次无命中浪费）。
- 逐入口在 handler 及其 import 的 runtime 模块 grep 强制关键字，分类：无强制/opt-in/强制；grep 为空或仅 schema/docstring 命中时须读到真实写路径再下结论。
- 仅对缺口入口实现门，复用兄弟入口既有习语：既有 verifier、fail-closed（账本不可读不写终局）、BLOCKED+reason_code+出口指路、异常出口（blocked/损坏诊断）分流不走门。
- TDD（含存量未验数据、损坏诊断优先级、fail-closed 用例）→ 全量回归 → 提交 → 用状态工具点名的完成能力（evolution_complete）登记并确认 pending 清零。

## Stop conditions
- 三要素齐全且逐入口现状分类完成，仅剩缺口入口待改；若所有入口均已强制，则报告无缺口而非硬改。
- 用户/回执要求的状态事实已由权威状态源验证（executing 数与回执一致）。
- 实现完成、回归全绿、完成登记已受理后停止，不再追加确认性搜索。

## Verification
- 每个现状分类结论可回溯到 handler/runtime 的具体命中行，而非仅工具描述或 docstring 文本。
- 新拒绝形态与记录的权威分类一致：BLOCKED+reason_code+逃生出口，账本不可读时 fail-closed。
- 回归全绿且 completion 能力（如 evolution_complete）已登记、pending_actions 对应项清零。

## Counterexamples
- 记录只有原则性要求、未点名任何入口/机制名 → 关键词锚定无从下手，目录/模块结构枚举是合理第一步，不应套用本方法。
- 强制关键字命中仅出现在 schema 参数定义或 docstring（如 builtin 包装层），真正消费在 import 的 runtime 模块甚至并不存在 → 命中数不等于强制存在，必须追写路径，否则会把未强制入口误判为已强制。
- 任务是新建一个写入口而非给既有兄弟入口加门 → 没有现状可分类，直接进入设计与 TDD，审计步骤无增益。
