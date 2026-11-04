---
method_id: resume-continue-via-untracked-delta-and-dangling-anchors-8337ade2b2e6
name: resume-continue-via-untracked-delta-and-dangling-anchors
description: 极简『继续』且 task_state 查询 miss 时，恢复面不是对证据库换措辞猜测搜索或全目录枚举，而是工作区 delta：以证据列表最新 acquired_at 为时间锚、已水合命令回执里的 cwd 为空间锚，一条 git status --porcelain 直接点名在途交付物（唯一未跟踪的当日文档；gitignore 天然滤掉 find 会带出的 pycache 噪声）。定位工件后，其头部自述与正文悬空的 §N 引用、『未实测』标记本身就是续做清单：grep 全部锚点补齐缺失章节、风格对齐上游同类文档、未实测项用项目权威环境转为已核。与『续跑沿命名 provenance』互补：那条用于上下文已点名文档，本条用于状态全丢、需先找回工件。
aliases: 继续但状态丢了怎么找回进度, 会话状态为空恢复未完成任务, 从git未跟踪文件定位在写文档, 断点续写补缺失章节, 按最后证据时间戳找最近改动, 继续指令无活动goal恢复现场
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:73172f2a-c1f6-4868-9611-d4af1d463c48:323:cd09f1c6707ebd46c04b
evidence_refs: learning:learn:5aceb4207a05
created_at: 2026-11-03T18:12:52.688743+08:00
updated_at: 2026-11-03T18:12:52.688743+08:00
---
## Trigger
收到极简续跑指令（如『继续』）且 task_state/会话状态查询返回 not found 或为空，而 list_evidence 仍可见上一会话的命令回执（含工作区路径与 acquired_at 时间戳）

## Discriminator
动手搜索前已可见的两个锚点：证据列表最新 acquired_at=上次活动中断时刻；已水合命令回执中的仓库根路径。二者把『哪里有什么在途工作』缩成『该 cwd 下 mtime 晚于该时刻的未跟踪文件』，通常唯一指向当日日期命名的交付物

## Short path
- task_state miss 后只做一次 list_evidence，读出最新 acquired_at=T 与工作区根路径；不做措辞猜测式 search_evidence、不 ls 全 docs 目录
- 在该 cwd 跑 git status --porcelain：未跟踪条目中最新修改的当日命名文档即在途交付物
- 读工件全文并 grep 其内部全部悬空 §N 引用与『未实测』标记，得到续做清单（本集=补写 §7–§12+两项实测）
- 对照上游同类文档章节结构补写缺失章节；『未实测』项用项目权威环境（如 .venv）实测转为已核事实
- 交付时显式列出仍需用户裁决的开放点，并闭合全部锚点

## Stop conditions
- 工件内所有被引用的章节锚点均已解析到实存章节，无悬空引用
- 工件自标的『未实测』项要么已实测通过、要么明确登记为待测残余
- untracked delta 为空或多个候选 mtime 不可区分时停止套用，转向权威 tracker/goal 或询问用户

## Verification
- 对定稿工件 grep 每个 §N 引用，确认全部指向实存章节
- 复跑文中声称已通过的测试须用项目 venv 并拿到通过回执，而非环境默认解释器
- git status 确认本轮改动集中在该单一在途工件，无范围外扩散

## Counterexamples
- 在途工作已提交、工作树干净：untracked delta 为空，应查最近提交与任务图而非 git status
- 多个并行任务留下多个未跟踪工件且 mtime 接近：时间锚无法区分，回退权威 tracker 或问用户
- 『继续』指纯对话决策或外部流程、工作区无对应工件 delta：不得硬套，应先向用户确认续做对象
