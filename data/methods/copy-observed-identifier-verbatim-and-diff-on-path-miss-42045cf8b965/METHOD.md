---
method_id: copy-observed-identifier-verbatim-and-diff-on-path-miss-42045cf8b965
name: copy-observed-identifier-verbatim-and-diff-on-path-miss
description: 当同一会话内更早的工具输出（git status、目录/registry 清单、成功回执）已逐字显示过目标 artifact 的路径或标识符时，读/操作目标应从该观察复制原文，而不是凭记忆重打；一旦 not-found，先做机械 diff（失败输入 vs 清单最近匹配），纠正后重试一次，再考虑 search_files/询问用户等宽搜索。把转写错误导致的 miss 从潜在全库枚举压缩为一次可验证的单步纠正。本集：清单已逐字列出 DESIGN-20261009-plugin-ecosystem-integration.md，记忆重打成 20260109 触发失败回执，且回执建议转入宽搜索。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e80a8cde-8a96-4b11-ad03-3f16341a32f5:652:3aacf896d907b456b586
evidence_refs: learning:learn:e1ba682cd351
created_at: 2026-10-09T11:54:43.479422+08:00
updated_at: 2026-10-09T11:54:43.479422+08:00
---
## Trigger
准备按路径/标识符读取或操作某个 artifact，且会话内已有工具输出显示过它的准确名称；或刚收到 not-found 失败而该目标路径是凭记忆输入的。

## Discriminator
更早的权威清单输出已包含目标的完整准确标识符（本集：第一步 git status 未跟踪列表逐字显示 docs/DESIGN-20261009-plugin-ecosystem-integration.md，早于失败读取），与失败输入仅存在机械转写差（20260109 vs 20261009）——knowledge-at-time 满足，无需事后答案。

## Short path
- 确定目标 artifact 后，先在会话内已观察到的清单/回执中定位其完整标识符；未知量：真实路径是什么
- 从清单逐字复制完整路径发起读取，不凭记忆重打数字或名称
- 若仍 miss：把失败输入与清单条目做机械最近匹配 diff，纠正后重试一次
- 读到文件并用其自证元数据确认与目标一致后，停止路径发现，转入内容分析

## Stop conditions
- 用清单原文路径读取成功，且文件内容自证匹配目标（本集：文档头部『日期：2026-10-09』与设计主题一致）
- diff 后清单中不存在任何接近匹配——此时才转入 search_files 或向用户求证，本方法到此为止

## Verification
- 纠正后的读取目标与会话内观察到的清单条目字符串级逐字一致（非语义近似）
- 成功回执的路径与文件自身元数据（头部日期/主题行）能自证这就是目标 artifact

## Counterexamples
- 会话内没有任何输出显示过目标名称（目标从未出现在清单/回执中）：需要正常 discovery，不应假装记得路径
- 清单已过期且存在已知并发写者（文件可能被重命名/移动）：先刷新清单再复制，不能拿旧清单当真值
- 失败回执表明原因不是转写错误（如权限拒绝、transient timeout、文件确实未创建）：机械 diff 无意义，按对应失败类别处理
