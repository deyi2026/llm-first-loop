---
method_id: arm-gates-from-execution-results-not-preexec-validation-7ec60b2296af
name: arm-gates-from-execution-results-not-preexec-validation
description: 门禁fail-open的共性是时间错位：授权flag在工具执行前的校验钩子里置位，失败的A（如受控read）仍会给后续不可逆B（如edit）放行；硬上界写后才拒则损害已发生。修法：校验钩子保持纯函数（只验参数与目标绑定，不mutate状态）；授权由执行器在真实SUCCESS回执后、从结果提取与目标绑定的证据token置位，失败/超时/无token/路径不匹配一律不置位；B消费时要求与armed token恰好相等且一次清空，拒绝任意非空串。不可逆写的硬上界改为写前保守字节上界证明（UTF-8多字节增长、replace_all全出现按最坏计），不能证明≤界即拒，dry-run不豁免。
aliases: read失败还armed, armed改结果驱动, 门禁flag执行前置位, 写前大小上界预检, 伪ref拒绝, edit前置真实read成功
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:2191:5d20fa1e71386e1123fc
evidence_refs: learning:learn:e41915e9c099
created_at: 2026-11-14T06:47:49.668546+08:00
updated_at: 2026-11-14T06:47:49.668546+08:00
---
## Trigger
实现或审查『先执行A、后凭A的成果授权不可逆动作B』的门禁（如受控read→edit、预计算→写盘），或fail-open反例/交叉审查点名armed状态在执行前置位、上界事后才拒

## Discriminator
门禁源码中可观察的时间错位三联征：授权flag在pre-execution校验钩子（dispatch前调用）内置位；消费侧只查『非空/已置位』而非与执行产物精确相等；硬上界在写入后检查或dry-run豁免——任一出现即fail-open，无需等运行期反例证明

## Short path
- 盘点门禁全部状态置位点与消费检查点，按『被守护事实何时权威化』分类：pre-fact（执行前置位=可疑）vs post-fact
- 校验钩子改纯函数：只验参数与目标绑定，不mutate任何授权状态
- 授权改由执行器在真实SUCCESS回执后置位：从结果本身提取与目标绑定的证据token存入armed状态；失败/超时/无token/路径不匹配一律不置位
- 消费侧要求与armed token恰好相等（拒绝任意非空串），一次消费即清空；重新授权需新的成功结果
- 不可逆写的硬上界改为写前保守字节上界证明：按最坏情况计（多字节增长、replace_all全出现、缺失按1计），不能证明即拒，dry-run不豁免
- 负测矩阵一次配齐：失败/未上报的A不授权、伪造token拒、二次B拒、fresh A重新授权恰一次；目标已超界/替换放大/多字节/写前拒

## Stop conditions
- 每个授权置位点都能追溯到真实执行SUCCESS回执或写前保守证明，且消费为精确相等一次性
- 负测矩阵全绿且既有预算/门禁回归不变；无法覆盖的面在交付中明示为阻断，不宣称完整

## Verification
- grep校验/断言钩子实现，确认无授权状态mutate（纯函数化）
- 负测断言拒绝发生在任何写入/dispatch之前（写前拒而非事后拒）
- 审查消费点：token比较为恰好相等且消费后清空，重放/伪串/任意非空均拒

## Counterexamples
- 校验与执行在同一同步原子帧、无失败窗口且无I/O（纯参数检查后立即执行）：pre-exec置位无fail-open窗口，不必强拆回调
- 授权语义就是allowlist本身、不消费任何执行产物的门禁：置位==校验是正确语义
- 操作可逆/幂等且已有事后对账与回滚机制：事后拒绝可接受，写前保守证明属过度工程
