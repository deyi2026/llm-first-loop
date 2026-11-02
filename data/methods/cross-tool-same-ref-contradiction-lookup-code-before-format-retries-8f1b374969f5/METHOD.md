---
method_id: cross-tool-same-ref-contradiction-lookup-code-before-format-retries-8f1b374969f5
name: cross-tool-same-ref-contradiction-lookup-code-before-format-retries
description: 当检索类工具（search_records/hydration）的回执刚逐字给出某记录的权威标识，而同会话的变更类工具（refine_experience/record_use）用该标识原样调用仍报『未找到』时，这不是输入格式问题而是跨子系统矛盾：先 grep 失败文案定位变更工具的真实 lookup/校验代码，再做一个有界存在性检查（文件在、stem 与 ref 一致）；若 lookup 只是 normalize+get 而工件存在，即判定两条链路 store 装配分叉，停止换格式重试，改走替代通道完成原目标并提交缺陷。本集可省去全库文件名扫描与第 5 次重试。
aliases: record_use 报未找到但搜索能搜到, 同一个 ref 检索命中但写入工具说不存在, 经验卡回执连败要不要再换 ref 格式, 工具说找不到但文件明明在, 回执工具和检索工具对不上
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:95500c09-6f2a-4a06-babc-88afd527db4d:226:dcd50ded72b26b44d9d3
evidence_refs: learning:learn:2067b44a6561
created_at: 2026-10-31T19:22:35.985831+08:00
updated_at: 2026-10-31T19:22:35.985831+08:00
---
## Trigger
检索回执已逐字给出记录的权威 ref（如 experience:<全 slug>），同会话变更/回执类工具用该 ref 原样调用仍返回『未找到指定经验』类失败；或同一工具已换过 ≥2 种 ref 写法失败、拿到 canonical 形式后再失败一次

## Discriminator
同一标识符在同一会话内被一个子系统成功解析（检索回执逐字打印它、标 active）、却被另一个子系统拒绝——输入格式被排除，剩余未知量只剩『变更工具到底比对什么』与『两链路是否指向同一 store』；失败文案字符串本身就是指向该比较代码的最短 provenance edge

## Short path
- 失败回执与检索回执做零成本对照：ref 是否逐字一致、检索是否标 active——一致即宣告输入空间已穷尽，不再尝试第 5 种写法
- 用失败文案原句在工作区做内容检索（1 次）直读命中处：确认 record 分支实际调用的 lookup 与所需校验维度
- 若代码显示额外校验维度（状态/命名空间/必填字段）→ 按合同改输入重发一次；若只是 normalize+get → 做一次有界存在性检查（按 ref 推导路径读文件头，或目录内文件名检索），确认工件存在且 stem 与 ref 一致
- 工件存在 + lookup 平凡 + 仍失败 ⇒ 判定 store 装配/链路分叉：停止重试，改走替代正式通道（如 settlement 账本）完成原目标
- 为该缺陷提一条可追踪修复建议（EVO/issue），引用两次回执的矛盾作为证据
- 立即给出用户的下一步建议，不把缺陷排查串行阻塞在收口报告之前

## Stop conditions
- 变更工具代码暴露可满足的额外校验维度，且改输入后一次成功
- 已判定装配分叉、经替代通道拿到完成回执（如 settlement committed/watermark），缺陷已记录
- 不存在能解析该 ref 的任何子系统（检索也 miss）→ 退回普通输入排查，本方法不适用

## Verification
- 结论同时持有三件证据：检索回执逐字命中同一 ref；工件存在且 stem 一致；变更工具 lookup 代码无额外身份校验
- 替代通道回执确认原目标（落账/回执）已完成
- 缺陷单引用两次矛盾回执，可被第三方以同一 ref 复现（一边命中一边未找到）

## Counterexamples
- 检索回执里的 ref 只是显示用截断串、非权威形式——原样使用失败可能仍是格式问题，须先取 canonical 形式
- 两工具指向不同 store 是架构设计（检索读公开镜像、写入走本地）——分叉非缺陷，正确动作是找对写入目标而非报 bug
- 失败原因是身份之外的业务校验（状态非 active、缺必填字段）——应按合同补维度重发，不应跳到 wiring 结论
- 没有任何兄弟子系统解析过该 id——无法排除输入格式，常规输入排查仍适用
