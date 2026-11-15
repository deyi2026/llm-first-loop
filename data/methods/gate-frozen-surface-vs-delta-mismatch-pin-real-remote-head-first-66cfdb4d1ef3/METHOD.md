---
method_id: gate-frozen-surface-vs-delta-mismatch-pin-real-remote-head-first-66cfdb4d1ef3
name: gate-frozen-surface-vs-delta-mismatch-pin-real-remote-head-first
description: 审查/准入闸以数值载荷（字符数、预计时长）拒绝、且回执冻结面文件清单与你已知本地 delta 明显不一致时，第一未知量不是『怎么收窄』而是『闸的 base 是不是真实远端头』：先做清单比对，不一致即一条 ls-remote 钉死真实远端头。远端为本地祖先 ⇒ 载荷确实大、fast-forward 安全，直接检索已验证的分段/拆分方案执行；push 类闸按设计不接受 paths 收窄，回执里的通用收窄指引对它无效，不要烧重试。tracking ref 的 [ahead N] 不定义 push 载荷。
aliases: push审查说材料超大, 闸冻结面和我的改动对不上, ahead数跟远端实际差很多, tracking ref是旧的, 审查载荷超预算先查真实远端头, 小审大推不让收窄路径
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d7d570d1-4d88-404b-9c9e-79d8afafaeed:600:66d05fa9b8b6e42e7e5e
evidence_refs: learning:learn:563c16423d2c
created_at: 2026-11-15T15:45:34.102288+08:00
updated_at: 2026-11-15T15:45:34.102288+08:00
---
## Trigger
准入/审查闸按载荷规模拒绝（reviewer 时长/字符数超硬上限）并给出冻结面文件清单，而清单含确证不在你本地 delta 内的文件；或拟直接以 tracking ref 的 [ahead N] 推断 push 载荷与远端状态时。

## Discriminator
回执冻结清单与 git diff --name-only <tracking>..HEAD 的差集非空且量大：冻结面出现 README/CHANGELOG/.githooks/旧批次产物等你未触碰的文件，而其中最新 commit 的文件集刚被上一条回执完整枚举可作对照 ⇒ 闸计算的 base ≠ 本地 tracking ref（本地引用过期或闸用真实远端头），一次 ls-remote 即可裁决。

## Short path
- 收到超限拒绝后，先取本地 delta 文件清单（一次 git diff --name-only <tracking>..HEAD），未知量：我要推的到底是什么
- 与回执冻结清单比对；不一致 ⇒ 未知量变为『真实远端头是什么』，用一条 ls-remote 钉死，不做任何收窄重试
- 用 merge-base 判拓扑：远端为本地祖先 ⇒ 载荷确实大且 fast-forward 安全；分叉 ⇒ 先合并再谈载荷
- 按闸类别核对合同（push 类不接受 paths 收窄），然后检索经验库找该类超限的已验证拆分方案（如按 commit refspec 分段过闸）并逐段执行
- 每段后核对远端头单调推进，直至远端头 == 本地目标 commit

## Stop conditions
- 权威远端头已钉死且与闸冻结 base 一致，超限规模已被解释（真大/假大）
- 已选定并开始执行与真实载荷匹配的方案（直推或分段），不再对同一闸重复收窄类重试

## Verification
- ls-remote 得到的远端头与闸冻结面起点一致；或 fetch 后重跑 precheck，est 塌缩回本地 delta 量级
- 分段执行中每段 push 后远端头单调推进，最终远端头 == 目标 commit，无段间资格/认证浪费

## Counterexamples
- tracking ref 确认新鲜（单 remote、刚 fetch 过）：超限面另有原因——scope 未带 paths 退化成 tree，正确修复是对接受 patch scope 的 kind 补 paths，不是查远端
- 你确实一次提交了百万字符级改动：无 base 错配，直接拆分，清单比对是浪费
- 冻结面里的构建产物/锁文件其实由你 delta 内的重建步骤生成：清单比对会误报，需按内容归属而非文件名裁决
