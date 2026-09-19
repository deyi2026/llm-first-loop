---
method_id: self-execute-review-contract-on-degenerate-tool-output-c1088a737f27
name: self-execute-review-contract-on-degenerate-tool-output
description: 当对抗式评审工具（如 grill_me）返回退化输出：壳结构完整（分层标题、使用说明）但第一层零实际问题时，不要跳过评审也不要循环重试。返回体中声明的'重点领域'清单本身就是评审契约：按每个已声明领域自问'该步骤在什么条件下失效'并强制逐条回答（跳过=假装完整）。对退化工具最多做一次输入显著改变的诊断性重试以区分输入触发 vs 工具损坏。落库时如实标注 verification_state=unverified、评审来源为自驱非工具产出。附带：历史检索在前两次各命中 10 条且已覆盖全部已知相关教训后停止，不再用变体词追查空命中。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5adf278f-405b-44db-95e5-3d3b94e1b8d9:929:c7443243ca1518a56db6
evidence_refs: learning:learn:6e490939226f
created_at: 2026-09-19T12:22:32.468542+00:00
updated_at: 2026-09-19T12:22:32.468542+00:00
---
## Trigger
调用评审/拷问/审查类工具对一份规程或设计做强制盘问时，工具返回结构壳但未生成实际追问内容

## Discriminator
返回体自身声明了评审契约：追问深度（3 层）与重点领域清单（分叉竞态处置、凭据链路、多 remote/worktree 混淆、推送后验证盲点、force push 与分支保护边界）已可见，而问题生成为空。这一事实当时即可把'等工具出题'缩成'按已声明领域自己出题'，无需依赖任何后续信息

## Short path
- 用 1~2 次 search_records 聚合 push 相关历史教训；两次各命中 10 条且已覆盖设备码授权/token scope/legacy origin/fetch 分叉/共享 checkout 等全部已知教训即停，不再追加 'git push'/'push' 等变体确认（该 episode 此处即为最早的搜索扩散）
- git remote -v; git branch --show-current; git status 核当前仓库事实（哪个 remote 真实、当前分支、脏状态），与教训对齐后成稿 v1
- 调用评审工具一次；若返回体含声明的重点领域但第一层零实际问题，最多做一次输入显著改变（如缩短草稿）的诊断性重试，验证是否输入长度触发
- 第二次仍同构退化 → 判定工具出题功能损坏，停止重试：按每个声明领域自问'这一步在什么条件下失效、我是否确认'，逐条强制回答，缺口映射回 v1 具体步骤（本例命中：单向分叉检查、force 竞态窗口、gh/git 凭据链不同步、裸 push/pull 禁令缺失、CI 未按 commit SHA 关联）
- 将盘问命中的缺口修订为 v2，save_experience 落库并显式标 verification_state=unverified（留待下次真实执行回填）
- 汇报中如实披露：评审为自驱而非工具产出、工具两连退化的事实，并建议下次先重试工具化拷问、仍退化则报程序故障

## Stop conditions
- v2 规程已落库，且验证状态（unverified）与评审来源（自驱/工具）均已如实标注
- 对同一退化工具的重试不超过一次诊断性重试，确认同构退化即切换自驱
- 历史教训检索在已覆盖全部已知相关主题后停止，不追加空命中的变体查询

## Verification
- 重读工具返回体，确认第一层确无实际问题行（只有使用说明壳）而非格式误读
- 自盘问每个声明领域至少有一条'我考虑了X，理由是Y/暂未考虑，需补充'式回答，且每条缺口能指回 v1 的具体步骤
- 落库记录包含 verification_state=unverified 与工具退化事实描述；下次真实执行时逐条核对哪些盘问命中为真、哪些为空转并回填

## Counterexamples
- 工具正常返回实际追问 → 直接逐条回答并用其逐层递进，不要用自驱盘问替代工具的适应性提问
- 工具返回纯错误或无任何声明领域结构 → 没有可自执行的契约，应报故障并降级为通用检查清单
- 评审对象为低风险常规操作且无事故史 → 五域全量强制拷问可能是空转，应按风险裁剪盘问深度
- 工具的逐层问题依赖上层答案生成 → 自驱执行丢失自适应提问价值，必须向用户披露此局限
