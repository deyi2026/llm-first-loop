---
method_id: gate-named-scope-minimal-restage-23984171754a
name: gate-named-scope-minimal-restage
description: 提交被 pre-commit 门禁（安全扫描/hook）拒绝且错误点名了违规文件/范围时，只在该点名范围内做最小调整，并按此前已枚举的精确文件清单显式 stage 后提交；绝不用 add -A/通配重扫全树作为修复手段，尤其当工作区存在大量未跟踪生成产物时。本例中宽扫把十万行级 run artifacts 卷入 staging，触发扫描超时并迫使撤销重做，而已存在的精确清单本可完全避免该循环。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:1651:136271c4da6184b8acc0
evidence_refs: learning:learn:c13f0cf9a84e
created_at: 2026-09-18T06:52:34.478619+00:00
updated_at: 2026-09-18T06:52:34.478619+00:00
---
## Trigger
合线前需落定未提交改动；提交被门禁拒绝且错误明确点名违规文件/范围；目标提交内容此前已被精确枚举成清单；工作区另含未跟踪的生成产物。

## Discriminator
门禁错误已把违规范围收敛到点名的单一文件/目录，且此前 inspection 已产出精确的目标文件清单——这两个当时已知事实足以把'该提交什么'从全树收敛为'已枚举清单减去点名范围'，无需任何新的宽收集。

## Short path
- 读门禁错误，提取点名 offender 与建议修复方式；未知量=哪些已暂存内容落在违规范围内
- 只对点名范围做最小移除（如 unstage 该目录），保持其余已暂存集合原样不动
- 不新增任何收集动作，直接提交剩余已暂存集合
- 下一笔快照按此前枚举的显式路径清单 stage；提交前用 diff --cached --name-only 与清单做集合相等校验
- 若门禁仍拦截，停止路径手术，升级为豁免登记/内容净化决策，不得以扩大 staging 范围重试

## Stop conditions
- staged 集合与枚举清单严格相等（路径与数量逐一匹配、无多余项）且门禁通过 → 立即提交并回到原计划
- 门禁拦截的是原子变更必需内容 → 停止拆分与重试，转为豁免或净化决策

## Verification
- 每次提交前将 git diff --cached --name-only 与预期清单做集合相等比对
- 提交后检查 status：未跟踪产物仍未入库、无清单外新文件被跟踪
- 门禁对最终提交集合显式输出通过

## Counterexamples
- 初始导入或全树快照，目标就是提交一切 → 宽 add 是正确手段，方法前提不成立
- 从未枚举过目标文件清单且工作区无生成产物 → 宽 add 后审查可接受，'清单已存在'前提缺失
- 点名 offender 是原子变更必需（如代码中含路径样测试字符串）→ unstage 会破坏原子性，应改内容或登记豁免而非移出
- 门禁为明显误报且文件必须保留 → 正确动作是豁免流程，而非任何 staging 手术
