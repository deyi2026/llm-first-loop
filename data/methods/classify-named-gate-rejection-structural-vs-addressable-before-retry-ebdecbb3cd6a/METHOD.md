---
method_id: classify-named-gate-rejection-structural-vs-addressable-before-retry-ebdecbb3cd6a
name: classify-named-gate-rejection-structural-vs-addressable-before-retry
description: 准入/审查闸返回结构化命名拒绝原因时，把 reason 字符串当作闸决策逻辑的权威陈述先做二分类：若命名的是调用方可修正的输入缺陷（大小超限、路径错、缺参数）→修正后重试；若命名的是结构性/策略性限制（如'远端 ref 不存在→首次推送无法计算审查 scope'）→阻塞源于请求所处状态而非命令形式，任何换拼写/换等价形式的同类重试都注定失败且零信息，应立即停止重试转入升级：呈现已完成事实+原样引用被拒原因+含闸外等价路径的选项。本集第二次 tag push（仅改 refspec 拼写）即属可省略重试。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7c026852-7867-4a41-9ab0-1340271874dc:847:3858f90621af8caa4bec
evidence_refs: learning:learn:6bf9e622a8f9
created_at: 2026-10-22T14:35:52.842810+08:00
updated_at: 2026-10-22T14:35:52.842810+08:00
---
## Trigger
动作被准入/审查闸拒绝且回执含结构化命名原因（reason/error code 字符串），同时存在'重试同类动作'的诱惑（换参数拼写、换等价命令形式）

## Discriminator
拒绝原因的语义指向：是请求内容缺陷（调用方可改）还是请求所处状态的策略限制（调用方不可改）。例如 reason 同时含 first_push/scope_unreviewable 与'远端 ref 缺失'语义，说明阻塞源于 ref 不存在这一事实而非命令拼写；再核对文档（工作流注释/发布文档）确认 canonical 命令形式已在第一次尝试中使用，即可在重试前断定任何同形重试必败。同一座闸可能既发可修正类拒绝（本会话早前的大小超限）也发结构性拒绝，必须按 reason 逐条分类，不能按闸的历史印象分类。

## Short path
- 收到命名拒绝 → 只读 reason 做二分类：可修正输入缺陷 vs 结构性/策略性限制（本例：first_push + unreviewable + ref absent → 结构性）
- 结构性：一次文档核对确认所用命令已是 canonical 形式，不存在语义不同（而非拼写不同）的替代路径
- 停止一切同类重试：不换 refspec 拼写、不换等价 push 形式再试
- 升级给决策者：已完成事实清单 + 被拒原因原样引用 + 选项（决策者本机执行 canonical 命令 / 显式标记为闸外动作的 API 等价路径 / 先修闸），不绕闸

## Stop conditions
- reason 分类为结构性且 canonical 形式已确认在用 → 不再发起任何同类动作，等待决策者裁决
- reason 分类为可修正缺陷 → 修正后仅重试一次，并对其新回执重新分类
- reason 泛型或瞬态（无解释、网络 EOF）→ 有界重探一次以取得可分类原因，仍无名则按瞬态失败处理

## Verification
- 发起第二次尝试前自检：新请求与被拒请求在语义上确有差异（不止拼写/形式），否则不发起
- 升级材料中原样引用 reason 字符串，且每个选项显式标注是否闸外动作
- 若最终走闸外等价路径（如 API 创建 tag ref），事后核对产物与 canonical 路径产物一致（同一 ref 指向同一 SHA）

## Counterexamples
- reason 为瞬态或无解释（网络 EOF、裸 403）时不适用：应做有界重试以获取可分类的命名原因，而非立即升级
- reason 命名可修正缺陷（如审查材料超大小上限）时不适用：修正载荷后重试即可到达，升级反而是绕远
- 闸本身有已知 bug、对可修正情况也发结构性 reason 时不适用：需按该闸历史行为校准分类，可能仍需一次受控重试验证
