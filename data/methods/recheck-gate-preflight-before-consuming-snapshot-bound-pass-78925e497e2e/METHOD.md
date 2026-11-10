---
method_id: recheck-gate-preflight-before-consuming-snapshot-bound-pass-78925e497e2e
name: recheck-gate-preflight-before-consuming-snapshot-bound-pass
description: 异步审查 PASS 绑定签发时的工作区快照，并在消费时按整树内容摘要重验；等待窗内任何写者——包括本 run 知识蒸馏管线滞后落盘的方法卡——都会让资格在消费瞬间失效并被 fail-closed 闸拒推。拿到 PASS 文本 ≠ 工作区未变：执行受闸动作（git push 等）前，重跑闸自身最廉只读预检并核对 HEAD==回执 push_src_commit；脏则先 flush+commit 折入漂移、对新树重签发一次，不把旧 PASS 消费成必然被拒的失败调用。与『执行旧建议前三锚点复核』卡互补：本卡管快照绑定资格的消费时点与自家后台写者，非旧建议前提新鲜度。
aliases: 拿到PASS先别急着推，再查一次知识闸, 审查等待窗里又落新方法卡怎么处理, 推送前重跑flush自检别白烧一轮审查, 资格绑的是快照，消费前先复核工作区, pre-push知识闸拒推后的正确收口顺序
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8641d508-e8f7-4b4c-86d8-c698c6927b74:1730:ce583c2988fbbc1e60e0
evidence_refs: learning:learn:63581014ef21
created_at: 2026-11-10T10:34:30.599606+08:00
updated_at: 2026-11-10T10:34:30.599606+08:00
---
## Trigger
准入/审查资格绑定工作区内容快照（回执含 candidate_sha、push_src_commit、revalidated_on_use=整树摘要），签发到消费之间隔分钟级异步等待窗，且环境存在滞后落盘的后台写者（本 run 的知识蒸馏管线、formatter）或共享工作区并发会话；待执行的是受闸动作（git push/merge/发布）。

## Discriminator
签发与等待期均已可见的三件事：①准入回执自声明消费时按整树内容摘要重验；②闸是 fail-closed（pre-push 知识闸对未入库资产拒推，其落地 goal 记录恰在等待期被读到）；③知识卡跨 turn 滞后落地已被实测——一次 flush 收走积压 9 张卡。三者合并 ⇒ 『PASS 文本到手』不等于『工作区仍等于被审快照』，消费前必须重验。

## Short path
- 配方照旧：flush → 回执窄通道 commit → --check rc=0 → 签发审查；注意预检只做在签发前是不够的
- 拿到 PASS 终态后、执行受闸动作前：重跑闸自身最廉只读预检（knowledge_flush --check），并核对 git rev-parse HEAD == 准入回执的 push_src_commit
- 预检干净且 HEAD 一致 → 立即原样消费，随后 ls-remote 核对 origin tip == 消费提交
- 预检脏（窗口内新落知识资产）→ 先 flush+commit 折入漂移，再对新树重签发一次审查；绝不拿旧 PASS 推送（整树重验必烧）
- 漂移来自外来在途编辑 → 停泊/上报而非代提交；同一窗口连续两次漂移 → 判定写者不静默，升级为机器层治理项（意图锁/窗口内暂存落卡），停止循环重审

## Stop conditions
- 预检 rc=0 且 HEAD 与 push_src_commit 一致：消费推送、核对远端 tip 后收口
- 同一资格窗口内第二次出现新漂移：不再签发第三轮审查，把后台写者治理作为阻塞项上报（对应意图锁/暂存落卡类演进）
- 漂移判定为外来活跃在途工作：转停泊+偏差上报路径，不折入自己提交

## Verification
- 消费前：预检命令 rc=0，且 rev-parse HEAD 与准入回执 push_src_commit 完全一致
- 消费后：ls-remote origin/main == 消费提交；再次 --check 仍为 0
- 曾被拒的资格不复用：失败回执后新 commit 必须走新一轮准入

## Counterexamples
- 同步闸：资格签发与消费近原子、无等待窗 → 机械 sha 校验已足够，消费前重查是冗余调用
- 闸只校验已提交状态（如 fast-forward 规则）、无 working-tree 敏感钩子 → untracked 新文件烧不掉资格，无需预检
- 预检命令昂贵或有副作用 → 只在消费时点做一次有界检查，不在等待期反复刷
- 漂移是他人会话活跃在途编辑（非自家管线已完成产物）→ 不 flush/commit 代收，走停泊+偏差上报（属三锚点前提复核卡的辖区）
