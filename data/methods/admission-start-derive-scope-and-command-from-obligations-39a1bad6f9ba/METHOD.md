---
method_id: admission-start-derive-scope-and-command-from-obligations-39a1bad6f9ba
name: admission-start-derive-scope-and-command-from-obligations
description: 启动材料冻结式独立审查/准入闸前的参数推导法：把闸 schema 的参数清单（kind/workdir/command/scope/paths）当作未知量全集，每个参数由一条明确义务导出——下游被闸动作→kind；仓库权威门禁脚本→command；用户验收义务是否引用候选 diff 之外的基线内容→scope（引用则显式 tree 整树冻结，否则 patch+显式 paths）。『基线必须保留』是确定性命题：冻结前用 git 级检查自证（基线为 HEAD 祖先、受保护路径与候选变更集不相交），不指望语义 reviewer 兜底；启动后只按 waiting_protocol 轮询到终态并核对 SHA 回显。
aliases: 启动独立审查前怎么定范围和命令, 基线必须保留时审查材料怎么圈, review_admission 启动参数怎么选, 冻结审查前的身份核对清单, 整树冻结还是只冻结改动路径
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b3644fd5-d92c-4eb0-a976-42dacec468b7:0:566e8f87bd61d9d07f2e
evidence_refs: learning:learn:9eba5c8a453a
created_at: 2026-11-10T08:33:57.626002+08:00
updated_at: 2026-11-10T08:33:57.626002+08:00
---
## Trigger
任务要求启动独立/异步的冻结材料审查或准入闸，且满足任一：任务文本把验收义务延伸到候选自身变更集之外（如『基线的钩子守卫/安装脚本/回执必须保留』）；闸 schema 提供 patch/tree 等材料范围选择且默认范围与义务不一致；启动前还不知道被闸动作的权威命令入口。

## Discriminator
启动时刻已具备三组事实足以直接定参，无需宽探索：(1) 闸完整 schema 已列出参数与 scope 语义（patch 只冻结声明 paths、tree 覆盖整树）——参数清单即未知量全集，与参数无关的版本/配置核对可省或并入同一次探测；(2) 用户义务逐字引用候选 diff 之外的基线路径 → scope 唯一合理取值为 tree；(3) 保留性可机械自证：基线祖先检查 + 变更集名单与受保护路径集求交为空，一条命令闭合，不必等语义审查回执。

## Short path
- 读闸完整 schema：确定必填参数、scope 语义、waiting_protocol，产出『还差哪些参数』清单
- 一次 shell 闭合全部身份未知量：HEAD 精确匹配、porcelain 为空、基线为祖先、受保护基线路径不在候选 diff 名单（保留义务自证）
- 义务→参数映射：被闸动作定 kind；仓库权威门禁脚本（ci_gate 类）定 command；义务超出候选 diff 则显式 scope=tree，仅候选自身则 patch+paths
- start 后按 waiting_protocol 配速轮询（wait≤120 → status），终态回执核对 child_id 与 candidate SHA 回显一致即停，汇报时区分自证检查 / Host PASS / 未代跑测试三层事实

## Stop conditions
- 身份或保留检查任一失败（HEAD 不匹配、脏树、基线不可达、受保护路径被改动）→ 不启动冻结，先解决身份问题
- start 回执已带冻结 SHA 与 child_id 且参数齐备 → 不再做与启动参数无关的仓库探索
- status 返回定性终态且回执 SHA/scope 与 start 一致 → 停止轮询进入汇报

## Verification
- 终态回执 candidate_sha256 与 scope.effective 同 start 回执一致、artifact_reviewed=true
- merge-base --is-ancestor 基线 HEAD 为真，且候选 diff 名单 ∩ 受保护路径集 = ∅
- 汇报明确：审查 PASS 只授权执行面≠已执行测试；资格一次性，消费时按冻结摘要复核

## Counterexamples
- 用户义务只覆盖候选自身改动、无基线保留要求 → patch+显式 paths 绑定更紧、材料更小；整树冻结反而放大材料与漂移面
- 候选以未提交工作树差分存在且快照哈希覆盖未跟踪文件 → 审查窗口内树会漂移，先稳定快照再谈范围选择
- 确定性守卫（行数基线/执行位/正则清单）的合规即使整树冻结覆盖了文件，也不该指望语义 reviewer 兜底——需单独只读跑守卫套件
- 任务只需查询已有审查终态（断点续跑）→ 走 status+产物清单恢复，不需要启动链
