---
method_id: guard-regression-fix-via-sibling-invariant-isomorphism-5df7611402b9
name: guard-regression-fix-via-sibling-invariant-isomorphism
description: 新加 fail-closed 守卫在默认布局下把普通（非特权）命令整体拒绝、被评审指出疑似回归时：先读守卫判定代码+默认路径推导证实拒绝全量触发；再看同一安全不变量在兄弟后端的既定保护形态——若为『遮蔽而非拒绝』（后置 tmpfs/deny 覆盖）且平台可复刻该机制，则做同构修复（拒绝改遮蔽，仅真正不可保护方向保留 fail-closed），并恢复旧测试原语义使其自然通过，而非改断言吸收新行为；顺带格式改动回退保持最小 diff，全量验证后把回归裁决理由显式写入报告交上级评审。
aliases: 新守卫误伤默认配置全被拒, 改测试掩盖回归怎么处理, 遮蔽代替拒绝的同构修复, fail-closed误伤普通命令, 沙箱后端保护策略对齐, 默认布局普通命令被守卫全拒
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:845bcf2f-a2e2-4d56-988d-5342125db812:226:ed78ca736b737f51cbac
evidence_refs: learning:learn:92ce499c5834
created_at: 2026-11-14T17:07:42.338438+08:00
updated_at: 2026-11-14T17:07:42.338438+08:00
---
## Trigger
新加的 fail-closed 安全守卫（或上级/父侧评审指出）在默认或常见配置下把非特权普通路径整体拒绝；同一安全不变量在兄弟后端/同文件中已有既定实现可对照。

## Discriminator
当时已知三条事实：默认布局使受保护 store 落在默认 workdir 子树内（守卫对普通命令全量触发而非仅特权路径）；兄弟后端对同一不变量采用遮蔽（bind/allow 之后追加 tmpfs/deny 覆盖）而非拒绝；守卫处注释自认『拒绝』是范围决定而非语义必需，且平台存在可复刻遮蔽的机制保证（如嵌套挂载父先子后、子覆盖父）。

## Short path
- 读守卫判定代码与默认布局推导，证实拒绝在默认部署对普通命令全量触发（未知量：回归是否真实）
- 检索同一不变量在兄弟后端的保护形态（未知量：既定模式是遮蔽还是拒绝）
- 既定为遮蔽且平台机制可复刻→把拒绝改为同构遮蔽（volume/bind 后追加 tmpfs/deny 覆盖 store），仅对真正不可保护方向（如 workdir 位于 store 内）保留 fail-closed
- 恢复旧测试原语义：正确行为应让旧断言自然通过、安全意图零削弱；新遮蔽语义用专项断言锁死（如构造顺序）
- 回退与语义无关的顺带格式/重排改动（如 argv 相邻行的等价改写），保持最小可审 diff
- 定向+全量测试与 lint/typecheck 通过后收尾，报告中显式写明『回归成立→同构修复而非改测试掩盖』的裁决链，交上级/独立评审

## Stop conditions
- 遮蔽机制有平台级顺序/覆盖保证（如嵌套挂载父先子后），默认布局下普通命令恢复既有可用性
- 旧测试以原始安全意图通过（断言未被削弱或改写）
- 不可保护方向仍 fail-closed，安全不变量未被放松

## Verification
- 旧守卫语义测试不改断言即通过
- 新专项断言锁死遮蔽构造顺序（mask 位于 volume/bind 之后）
- 全量回归套件 + lint/typecheck 全绿

## Counterexamples
- 平台无『子挂载覆盖父挂载』语义或顺序无保证时，拒绝才是正确修复，遮蔽是虚假修复
- 被拒方向设计上必须 fail-closed（如 workdir 本身在 store 内、host-grant 特权路径）——保持拒绝不动
- 无兄弟实现可参照、或兄弟同样选择拒绝时，『过度拒绝』可能正是不变量本义——应上报裁决而非自行放宽
- 不变量没有遮蔽等价物（如网络出站禁令、能力裁剪）时，不适用遮蔽/拒绝同构判断
