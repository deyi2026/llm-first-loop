---
method_id: execute-change-spec-at-cited-anchors-resolve-modules-by-symbol-grep-1107f356e6f2
name: execute-change-spec-at-cited-anchors-resolve-modules-by-symbol-grep
description: 执行已批准的变更规格（evolution/工单）时，检得的规格记录即使被截断，其可见部分通常已引用 live 工作区的精确 file:line 与符号名——这些引用本身就是本次任务的目标文件清单，『改哪些文件』这一未知量在检索命中时即已闭合。正确动作：直接对锚点做有界读取并核对当前代码是否仍符合规格前提；对规格点名但路径未知的模块，用已读到的装配/调用符号做一次定向 grep 反查真实路径，不猜子目录、不做全局文件名搜索（含 .releases 快照镜像的仓库只会灌回过期副本）。本集的 20 条 .releases 命中与 subagent/factory.py 误猜均为可消除绕行。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1b498f1a-b510-4497-be53-2ae3460c91be:400:2b5b2ba9d8400a6589de
evidence_refs: learning:learn:37c5789ed270
created_at: 2026-10-21T07:07:48.284865+08:00
updated_at: 2026-10-21T07:07:48.284865+08:00
---
## Trigger
接手执行一条已批准的变更/演进任务；登记簿检索已命中其规格记录（内容可能截断），且规格可见文本引用了工作区相对路径的 file:line 锚点或明确的函数/常量符号名

## Discriminator
规格记录可见部分是否已枚举出足以覆盖全部改动点的 file:line/符号引用。若是，文件定位未知量已闭合，任何文件名/目录级发现都是在重复求解已闭合的未知量；唯一剩余的定位未知量是『被点名但未给路径的模块在哪』，其判别信息在已读代码的 callsite/import 符号里，不在文件名里

## Short path
- 按对象 ID 查登记簿确认执行状态（本集：evolution_exec → executing unverified），与人工回执一致即闭合状态未知量
- 对规格引用的每个 file:line 锚点在 live 工作树做有界 span 读取，核对前提仍成立（如 :490 附近确有静态上限、_classify_reviewer_failure 仍存在）；行号漂移或锚点被截断时用规格点名的符号在文件内重锚定
- 对规格点名但未给路径的模块（如 factory.py），用已读到的装配符号（attach_runner、context_limits_resolver）做一次定向 grep，由 callsite/import 反查真实路径与装配点，替代子目录猜测与全局文件名搜索
- 在已锚定事实上实现变更并跑针对性测试/独立审查；每个规格前提都有 live 代码回执支撑后停止一切发现动作

## Stop conditions
- 规格的全部代码前提已在当前 live 树核实（常量/函数/装配点与规格一致，或差异已归因为提案后演进）
- 改动点文件集全部由『规格引用锚点 ∪ 符号反查』确定，不存在来源不明的文件
- 针对性验证（新单测、爆炸半径测试、独立审查）通过

## Verification
- live 读取回执与规格声称逐一对上：锚点附近确有该常量/函数定义（192_000、_classify_reviewer_failure 等）
- 符号反查所得路径可被调用图闭环：该文件确实装配/调用目标模块（factory.py 调 attach_runner 并传入 context_limits_resolver）
- 最终 diff 的文件集 ⊆ 规格引用文件集 ∪ 反查定位文件集

## Counterexamples
- 规格锚点严重过时：提案后经历大重构、文件与行号全漂移——锚点降级为线索，应以符号重定位为主，适度结构发现是必要的（当前定义+callsite 才是真值）
- 规格为纯 prose、不含任何 file:line/符号引用——无锚可依，目录/文件名/符号层面的发现才是正当的第一步
- 任务只要求核实状态、不落地代码——本方法不适用，直接按 ID 查登记簿即可
- 仓库无快照镜像且文件名全局唯一——一次文件名搜索即可定位，本方法的差异化收益趋近于零
