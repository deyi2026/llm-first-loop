---
method_id: checker-probe-empty-vs-verified-ref-audit-root-binding-e4438c62fa99
name: checker-probe-empty-vs-verified-ref-audit-root-binding
description: 门禁/队列机检失败且失败签名是『探测某 ref/资源为空』，而同一 run 早前回执已证明该 ref 真实存在未移动时，第一未知量不是产物是否合格，而是检查器当时绑定到哪个根/快照：先只读核对检查器的 root/cwd 解析；确认错位（如解析到无该 ref 的 detached 发布快照）即定性为装配缺口，不原样重跑错误入口、不反复 requeue、不把失败算到候选头上；用修正后的正确绑定原样重跑同一套检查保持等价，全绿后继续流程，并把工具缺口登记演进。
aliases: 队列说main不存在, probe为空但分支明明在, 闸门误报先看它在哪个目录跑, 检查器把发布快照当工作区, 工具结果跟已核实事实打架, 宿主解析错仓库根
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:2199:924641ed085367901136
evidence_refs: learning:learn:d31ed0246698
created_at: 2026-11-08T14:30:11.430861+08:00
updated_at: 2026-11-08T14:30:11.430861+08:00
---
## Trigger
队列/门禁机检回执显示探测目标 ref/资源为空并判 fail，但本 run 早前的权威回执（rev-parse/porcelain 等）已证明该 ref 存在且状态未变

## Discriminator
同一 run 内两张回执直接矛盾：早前 rev-parse 已见 main 存在、树 clean；机检却探测为空 ⇒ 差异只能出在检查器一侧的仓库根/快照绑定，而非共享 git 状态或候选产物

## Short path
- 拿到机检失败回执后，先与本 run 早前的 rev-parse/status 回执逐项对照，确认矛盾点是『存在性』而非内容层失败
- 只读检查失败检查器的环境绑定：它实际解析到的 root/cwd 是哪个目录、该目录是否包含目标 ref
- 若绑定错位（指向无该 ref 的 detached/发布快照），定性为装配缺口而非代码失败：不重跑同一错误入口，不把失败记到候选头上
- 用修正后的正确 root 原样重跑同一套机检（检查等价），逐条留存真实退出码与输出
- 全过后继续收口流程；同时把『工具层 root 解析错误/无 requeue 入口』登记为演进缺口

## Stop conditions
- 修正绑定后原样重跑的同一套机检全部真实通过，且与既有 PASS/干净回执一致
- 对照后发现 ref 确实变了（如 main 已被并发推进）：停止归因于检查器，转重新对齐基线并复验
- 缺口已登记演进，未留下任何隐性绕过

## Verification
- 逐条比对重跑前后的机检项集合与判定逻辑完全一致，无增删跳过
- 指认失败回执中检查器实际 root/cwd 与权威工作区 root 的具体差异并留痕
- 等价重跑的退出码与完整输出真实落盘、可独立审计

## Counterexamples
- 探测为空源于 ref 真不存在或已被并发会话移动：先重验权威状态，而不是怀疑检查器
- 失败发生在内容层（测试红/静态诊断新增）：环境绑定无关，须修代码或复验候选
- 本 run 没有早前证明该事实的回执：先用一次便宜调用核实事实本身，再决定归因方向
