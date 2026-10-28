---
method_id: locate-session-declared-deliverables-via-present-files-record-before-fil-5ff35633a5e8
name: locate-session-declared-deliverables-via-present-files-record-before-filename-search
description: 用户按名引用本会话早前已交付/已展示过的工件（如 present_files 声明过的裁定书、状态文件、设计文档）时，把交付声明记录当作权威定位器：先在 evidence 台账检索该文件名对应的 present_files/交付记录，取其精确路径，再做任何文件名搜索。本集先两次 search_files（一次无匹配、一次被 40 条 .releases 镜像里同带 GATE 字样的无关文件刷屏），随后 search_evidence 一次命中带路径/大小/mtime/描述的声明；且已读文档正文自引用的 pool.jsonl 路径也可直接推导，无需再搜。与『镜像+exclude 下先用在手输出推导路径』卡互补：本法在有显式声明记录时更先、更窄地触发。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:e47f7009-17d2-450f-91a7-d4daf1887e55:1213:5e6b84bb1066a80495d5
evidence_refs: learning:learn:40f82f6d49e8
created_at: 2026-10-21T10:57:05.076012+08:00
updated_at: 2026-10-21T10:57:05.076012+08:00
---
## Trigger
用户按名引用一个本会话已产出/已声明交付的工件（曾出现在 present_files、交付回执或写入路径回显中），需要其精确路径开始读取/编辑；工作区含发布快照镜像目录或 exclude，文件名搜索易无匹配或被大量同名同味文件淹没

## Discriminator
该文件名是否已出现在本会话的交付声明记录里（evidence 台账 present_files 记录：精确路径+字节数+mtime+用途描述）。此事实在首次搜索失败时即已存在，可直接把『全库哪个文件是目标』缩成『声明记录里这一条路径』，完全绕开镜像同名干扰

## Short path
- 用户点名某早前交付物 → 未知量：精确路径；先检索本会话 present_files/交付声明（对该文件名做 search_evidence），而不是重发或放宽文件名搜索
- 命中声明记录 → 直接 read_file 声明给出的精确路径；未知量：目标段落实际内容
- 已读文档正文或同批声明中已写明关联数据文件路径（如 pool.jsonl 副本目录、同级状态文件）→ 按引用路径直读，不再发起第二次文件名搜索
- 对照 read_file 回执（workspace_path_state=current_match、size/sha 与声明一致）确认非 .releases 镜像副本后开始编辑
- 核验脚本跑原始记录取得实测数字，写回声明路径上的真身文件

## Stop conditions
- 精确路径已由声明记录确认且文件系统存在、大小/时间一致 → 终止一切定位搜索，进入读取/编辑
- evidence 检索确认该文件名从未在本会话声明/交付 → 放弃本法，转常规发现（live-tree 优先或存储命名方案解析）

## Verification
- read_file 回执路径与声明路径逐字一致且 workspace_path_state=current_match，确认编辑未落在镜像副本上
- 声明记录中的 size/mtime 与实际读取回执一致；不一致视为陈旧声明，回退存在性校验与搜索
- 涉及统计数字的段落以重跑脚本对照原始记录核验，不转写上一轮口头汇总

## Counterexamples
- 目标文件从未在本会话声明或交付（外部文件、来源不明）→ 声明检索必空，应走目录枚举/命名方案发现，本法不适用
- 工作区健康：无镜像目录、无 exclude 且文件名唯一 → 一次文件名搜索即可闭合，先查声明反而是多余一步
- 文件在声明之后被移动/重命名（声明陈旧）→ 声明路径 fs 校验失败，必须回退到树内搜索而非沿用旧路径
