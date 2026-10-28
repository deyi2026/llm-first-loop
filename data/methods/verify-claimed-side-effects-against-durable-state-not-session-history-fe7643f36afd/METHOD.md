---
method_id: verify-claimed-side-effects-against-durable-state-not-session-history-fe7643f36afd
name: verify-claimed-side-effects-against-durable-state-not-session-history
description: 当一条完成声明（note/回执）断言某副作用已发生（发布、部署、登记、全量门禁通过）并点名具体锚点（commit 号、release head、job id、登记 ID）时，逐锚点对照权威落盘状态源核验：release 快照目录、部署 git_head/lag/进程存活、append-only 审计日志。绝不以『本会话未执行过该动作』作为事件未发生的证据——执行者可能是其他会话、人工或自动化。对输出已被跨进程回收的 job，凭退出码 + fail-fast 脚本语义（set -euo pipefail）即可判定，不必重跑或扩大排查。核验通过后如实报告遗留项（如审计中的 probe 记录、未登记 WIP 导致的确定性门禁失败）。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:1491:56ef8ac3d68805ebe655
evidence_refs: learning:learn:c23f32c593ee
created_at: 2026-10-18T11:03:15.165488+08:00
updated_at: 2026-10-18T11:03:15.165488+08:00
---
## Trigger
需要核验他人/上一轮留下的完成声明（如『已随 X 发布』『全量 ci_gate 通过』『已登记』），且声明中含可查锚点：具体 commit、release head、job id 或登记 ID；或工具回执明确提示『勿仅凭本回执，以落盘交叉验证』。

## Discriminator
声明点名了精确锚点，且系统存在该类事件的权威落盘状态源（release 快照目录、含 git_head/lag_generations/进程存活的部署状态、append-only 审计日志）。此时『我这个会话没发出过 publish 调用』不构成任何反证——它只说明执行者不是本会话。

## Short path
- 把声明拆成可验锚点清单：commit 号、release head、job id、登记 ID
- 逐锚点查其权威状态源：审计日志→登记是否落盘；job 终态退出码 + fail-fast 脚本语义→门禁是否通过；release 快照目录 + 部署 git_head/lag/进程存活→是否已发布
- 对输出已被回收的 job：以 exit=0 + 脚本 set -euo pipefail 推断通过，不重跑、不展开额外排查分支
- 不为『本会话未执行过该动作』生成待证伪假设；只有状态源与声明矛盾时才提出质疑
- 全部锚点一致即停，输出确认 + 如实列出遗留项（append-only 日志残留记录、被本地排除且未登记 durability registry 的 WIP 会持续打红门禁）

## Stop conditions
- 声明中每个锚点都已在对应权威状态源得到一致确认
- 发现状态源与声明的具体矛盾并已如实报告，不再继续推测
- 声明无任何可查状态源：停止自查，转为向声明者求证，而非用会话历史推断

## Verification
- release head 与 .releases 快照目录、部署状态 git_head 三者一致，且 lag_generations=0、进程存活、restart_required=false
- job exit=0 且门禁脚本为 set -euo pipefail（或等价 fail-fast），据此推出全环节通过
- 审计日志存在对应登记记录，时间与内容同声明一致

## Counterexamples
- 声明是一次性手工操作、无任何落盘状态源（『我在本地跑过一次脚本』）→ 无法核验状态，只能询问执行者；此时会话历史反而可能是唯一线索
- 快照存在但部署落后（stale snapshot 或失败回滚残留）→ 存在性不等于生效，必须再查 live 状态匹配才可确认
- 门禁脚本非 fail-fast（无 set -e、部分步骤容错）→ exit=0 推不出全步骤通过，需逐环节证据
- 核验的是本会话自己刚发出的动作且关心其中间行为 → 会话自身 action 记录才是权威，落盘状态可能滞后于执行
