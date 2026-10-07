---
method_id: locate-unimplemented-feature-host-via-spec-cited-anchors-2752753f5c23
name: locate-unimplemented-feature-host-via-spec-cited-anchors
description: 为『尚不存在于代码中的新功能』定位宿主模块/插入点时，规格词汇不能当搜索键——按构造缺失，命中只会是 evals/tests 侧引用。改沿三条已存在的锚点边：① 规格文档正文引用的 file.py:line → search_files 定位真实路径；② 被引文件的父目录 ls 得兄弟模块；③ 前置功能 commit 的 --name-only 文件清单。已出现 2 次规格词内容搜索零命中即强制换锚，禁止第 3 次同源换词重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9571992a-d742-4a48-824b-b1f635b8674f:961:d9cf29e5c065bc306c8f
evidence_refs: learning:learn:3ff2e8ee79d6
created_at: 2026-10-07T11:57:17.213827+08:00
updated_at: 2026-10-07T11:57:17.213827+08:00
---
## Trigger
拿着一份描述待实现新功能的规格/设计文档，需要定位其宿主模块与插入点，并开始把规格词汇（如 post_capture/animation_frame）当作内容搜索键，尤其已出现连续零命中时。

## Discriminator
当时已可见：(1) FR-2 是未实现的新功能，其规格词汇按构造不可能存在于实现代码中，此前 search_files 命中的全是 evals/ 测试侧产物（browser_wait_object_state 引用面）；(2) 刚 grep 过的设计文档正文已引用具体实现锚点 perception.py:1527-1652 与 attestation.py——这是指向宿主模块的现成 provenance 边。

## Short path
- grep 规格文档抽取其引用的实现锚点（file.py:line、点名的模块/函数、验收与 NFR 节点名的文件）；未知量：宿主模块在哪
- search_files pattern=<被引文件名> 取真实路径，再 ls 其父目录列兄弟模块；未知量：dispatch/插入点所在文件（同法可用 git log --name-only 查前置功能 commit 的 touched files）
- 在宿主模块内 grep capture/dispatch 流程并读对应片段；未知量：确切插入窗口（本集为 dispatch→post-capture 零间隔处）
- 规格条目与源码窗口一一对应后停止发现，转入设计与实现

## Stop conditions
- 被引锚点文件已在源码中定位，且其目录内可见插入点所在文件并完成片段阅读
- 连续 2 次以规格词汇做内容搜索零命中即换锚点策略，不允许第 3 次同源换词

## Verification
- 文档引用的路径/行号与源码实际符号一致（被引文件真实存在于引用所指位置）
- 插入点在真实调用链上被 grep/read 直接证实，而非 evals/tests 或 fixture 副本
- 宿主目录 ls 结果覆盖文档点名的全部模块，互证无遗漏

## Counterexamples
- 功能是对既有行为的修改/调参（如调整已存在的 wait/重试逻辑）时，规格词汇本就存在于代码中，直接内容搜索更快，不必绕锚点
- 规格文档无任何 file:line 引用且 git 历史与该功能无关时，改走入口邻接：工具/类名→registry→builtin 实现文件
- 目标是完全孤立的从零新建文件、不接入现有调用链时，锚点搜索无意义，直接创建即可
