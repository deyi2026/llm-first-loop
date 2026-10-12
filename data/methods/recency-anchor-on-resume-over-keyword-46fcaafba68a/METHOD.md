---
method_id: recency-anchor-on-resume-over-keyword-46fcaafba68a
name: recency-anchor-on-resume-over-keyword
description: 任务以『继续』类指令恢复时，锚点文档（上次会话刚产出的 spec/设计）优先用 recency/provenance 元数据定位：ls -lt 取最近文件、git log 佐证提交，而不是先用带歧义短标识符（R3、P1 等）做全库内容搜索；一旦发现关键词命中的是共享同名标识符的另一套文档族，立即切换检索轴（mtime/git/命名约定），不要在同一轴上继续换词重搜。这能把『所有含该 token 的文件』缩成『最近产出的那一个 spec』，省去多轮无效关键词枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fc0ed66c-e669-41c4-94d7-7e05031bbac6:409:569f950084ca95ce8deb
evidence_refs: learning:learn:9fe01c2b81ab
created_at: 2026-09-22T17:33:04.790208+00:00
updated_at: 2026-09-22T17:33:04.790208+00:00
---
## Trigger
任务以『继续/恢复上次会话』开场，且上次刚落盘过 spec/修复包文档；或内容搜索命中的全部是共享同一短标识符（如 R3）但主题无关的另一套文档族

## Discriminator
首次关键词搜索结果全部来自另一文档族（同名 R3 但主题是缓存/RECOVERABILITY，与本次 service-control 修复包无关），证明该 token 在仓库内过载、不可判别；同时『继续』上下文保证目标文档是最近产出——这两条当时已知事实足以把候选空间缩到『按 mtime/git 取最近一个 spec』

## Short path
- 由『继续』推出锚点文档来自紧邻的上次会话 → 未知量：最近产出的 spec 是哪个文件
- ls -lt <docs目录> | head（或 git log --oneline -- docs/）按修改时间/提交取最近候选，git 提交信息（如『落盘 …spec』）作第二重印证
- 读该 spec，确认其术语与当前任务子域一致（目标子系统、缺陷编号），定位目标小节（如 R3）
- 按 spec 点名的文件与符号做定向 grep/sed 核代码现状，识别 spec 与实际差异
- 事实核齐即输出设计裁决与 diff 草稿，停止发现

## Stop conditions
- 锚点文档已通过 mtime+git 提交信息双重印证，且内容明确覆盖任务词汇与目标子系统
- 用户消息已含明确路径/ID 时跳过定位直接读取
- 定向 grep 已确认代码现状与 spec 的全部差异点，进入方案输出

## Verification
- git 最近提交信息与文件名/主题一致，mtime 为目录内最新
- 读到的 spec 小节明确引用本次任务的目标文件与缺陷（而非同名另一族文档）
- 代码 grep 得到的符号/签名/行为与 spec 引用的行号与机制对得上

## Counterexamples
- 目标是很久以前的稳定参考文档（非上次会话产物）：recency 排序无效，应回到关键词/语义检索
- 标识符在仓库内唯一无碰撞：第一次关键词搜索即命中，无需换轴
- 仓库刚经历批量格式化/文件搬迁，mtime 大面积同新：改用 git log -S 或提交消息过滤
- 用户消息已直接给出文件路径或链接：直接读取，不做任何检索
