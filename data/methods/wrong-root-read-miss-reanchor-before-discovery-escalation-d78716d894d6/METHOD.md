---
method_id: wrong-root-read-miss-reanchor-before-discovery-escalation-d78716d894d6
name: wrong-root-read-miss-reanchor-before-discovery-escalation
description: 多 worktree/镜像仓只读审查中，read_file 用相对路径读任务点名的文件，回执报『文件不存在』（常附 TTL 缓存缺席登记并建议改用 search_files 或向用户求证）时，先比对回执打印的解析后绝对路径前缀与已确认的交付 worktree 根。前缀不一致说明是 read 工具与 shell cwd 锚定根不同的路径伪影，用 worktree 绝对路径原样重发一次即可；不要升级为全库搜索或向用户求证。只有重锚定后（前缀已一致）仍 miss，才按真缺失走定位手段。可程序化：提取回执路径前缀 vs git rev-parse --show-toplevel 比对。
aliases: worktree里读文件报不存在, 路径解析到主仓库不是worktree, read_file相对路径找不到文件, 缓存说不存在但diff里有, 多checkout读文件路径错根, worktree绝对路径读文件
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8f7a9539-1739-4119-af7b-e783613d8918:0:6b81211ece6106643bd4
evidence_refs: learning:learn:9644b4237aac
created_at: 2026-11-14T10:40:30.365081+08:00
updated_at: 2026-11-14T10:40:30.365081+08:00
---
## Trigger
多 worktree/镜像仓审查中，按 git diff 结果用相对或主仓路径 read_file 一个刚被确认存在的文件，回执报『文件不存在』，且附带 TTL 缓存缺席登记与『改用 search_files/向用户求证』的建议

## Discriminator
失败回执打印的解析后绝对路径前缀 ≠ 已确认的交付 worktree 根（任务书给出的 worktree 路径、shell 回执 cwd、HEAD/tree 核验一致的那份），而该文件刚出现在 git diff --name-only 中——miss 是工具路径锚定伪影而非存在性结论，git 侧机械存在性证据优先于缓存登记

## Short path
- 比对回执解析路径前缀 vs 任务书/shell cwd 的 worktree 根，确认是锚定错根
- 用 worktree 绝对路径（根+相对路径）原样重发同一 read_file，不换措辞、不 search_files、不向用户求证
- 后续本次会话所有 read_file 一律带 worktree 绝对前缀（或先 git rev-parse --show-toplevel 取根）
- 只有重锚定后仍 miss（前缀已一致）才升级为 search_files/求证

## Stop conditions
- 以正确根前缀成功读到目标文件，内容锚点（行数/version token）与 git 侧一致
- 或 git 侧证实该路径在当前 HEAD 下确实不存在，此时缓存登记可信，转入定位手段

## Verification
- 成功读取的文件 label 前缀与 worktree 根一致
- git rev-parse --show-toplevel 或 git diff --name-only 交叉证实文件在交付 checkout 内存在

## Counterexamples
- 单 checkout 仓库：相对路径锚定本就正确，miss 即真缺失，应换定位手段而非重锚定
- 回执解析路径前缀已与正确 worktree 根一致：TTL 缓存登记有效，重锚定无用
- 期望文件确实尚未创建（产物未生成）：重锚定不解决问题，应回到生成侧排查
