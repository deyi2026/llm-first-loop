---
method_id: count-scope-vs-round-cap-before-bounded-reviewer-spawn-8ecefaf517d9
name: count-scope-vs-round-cap-before-bounded-reviewer-spawn
description: 派发固定轮次上限的只读 Reviewer 子代理前，brief 的强制阅读集在文本里已可枚举（目录 glob 全量代码＋具名 receipt/判据文档＋逐项判据）。先做账：工件数×（定位＋读取）＋最终综述轮 vs 轮次上限。余量明显不足时不要指望 child 自己挤出来——按证据类别拆成先后两个 child（代码闸 pass＋receipt/判据 pass）、把精确路径预写进 brief 消掉定位轮、或向上请求提高上限；拆分时每个 pass 带冻结 SHA/tree 一致性核对以便裁决可合并。预算耗尽会把审查变成『强制项未读』的 fail-closed BLOCK，被迫二轮补审。
aliases: 审查子代理预算耗尽中途停, 阅读清单太长一遍读不完, 派审查任务前先数文件数, 审查报告因没读完而不完整, 范围和轮次数对不上
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:520bb4af-a364-4194-87f6-f98bae40353c:0:020927d5f989c2ec6751
evidence_refs: learning:learn:dd93165acaca
created_at: 2026-11-17T17:43:26.284004+08:00
updated_at: 2026-11-17T17:43:26.284004+08:00
---
## Trigger
准备 spawn 一个带固定轮次上限（max_rounds 类）的只读审查子代理，且 brief 的必读清单由目录 glob＋多份具名文档＋逐项审计判据组成，估算工件数与轮次上限同一量级。

## Discriminator
spawn 前即可从 brief 文本算出：必读工件逐件需≥1 次定位＋1 次读取，另需综述轮；当强制读集规模逼近轮次上限、又未预置精确路径时，任何检索失败都会挤掉尾部必读项。本集 child 正因此耗尽预算，代码全读但具名 receipt/判据文档未读，裁决退化为完整性级 BLOCK。

## Short path
- 把 brief 中的目录 glob 展开为具体强制工件数（可用 scoped 枚举则先枚举，不靠猜）
- 做预算账：工件数×（定位＋读取）＋综述轮 vs 轮次上限，要求留出可吸收检索失败的余量
- 余量不足时三选一：按证据类别拆成先后有界 child（代码闸 pass→receipt/判据 pass）；把精确路径与锚点预写进 brief 消掉定位轮；向上请求提高轮次上限
- 拆分时在两个 pass 的 brief 中都写入冻结 HEAD/tree 一致性核对与前一 pass 结论摘要，保证裁决最终可合并成单一判定
- 结算时核对 child 收敛说明与 rounds 用量：『预算耗尽＋强制项未读』即本次派发账算错，把实际轮次/工具消耗记为下次账算的校准参数

## Stop conditions
- 账算显示余量充足（如强制工件数远小于上限且路径已精确）：按原 brief 直接派发，不拆分不加账
- 轮次上限与审查范围均为请求方硬约束、且裁决要求单一上下文交叉比对全部证据：不拆分，改为协商提高上限或明确接受 fail-closed 部分裁决并声明缺口
- child 结算后强制项全覆盖、无预算耗尽收敛说明：本次派发账算正确，无需后续动作

## Verification
- 结算核查：child 终态报告无『强制工件未读』类条款，清单项逐项在裁决中有着落
- 拆分场景：核对两个 pass 审的是同一冻结 SHA/tree，合并裁决前确认两 pass 之间无新提交漂移
- 留存本次账算 vs 实际消耗（rounds、工具次数）的差值，作为下一份 brief 的派发校准数据

## Counterexamples
- brief 仅含少量精确路径（≤5）且轮次上限宽松——账算明显满足，套用本方法只增开销不降风险
- 审查 child 的工具集含批量检索（grep 类），一次调用可覆盖多个清单项——按文件件数计账会高估消耗，此时账算应以估算调用数而非文件数为准
- 裁决必须由单一头脑跨代码与 receipt/判据文档逐条比对（如隔离性 receipt 对照实现），拆分会破坏审计要求——此时不拆分，直接走提高上限或 fail-closed 部分裁决并声明
