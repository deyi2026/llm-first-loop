---
method_id: verify-fix-live-via-layered-artifact-truth-not-timestamps-bdfe00aba284
name: verify-fix-live-via-layered-artifact-truth-not-timestamps
description: 验证"某修复是否已修好/上线"时，按部署链分层各取机械真值：源码层=直接读被点名文件的点名行（勿先全库搜索，避免 .releases 快照副本淹没工作区真值）；提交包含=git merge-base --is-ancestor；构建产物=对 bundle 字节直接 grep 修复的 minified 特征并核对与源码结构等价，绝不以 dist mtime 与 commit 时间比较推断产物新鲜度（先改→构建→后提交属常见顺序，时间戳无效）；线上层=fetch 运行服务实际分发的 bundle 与含修复产物对齐。manifest 缺产物哈希时跳过 manifest 直接端到端取。任一层确定性失败即停止并报"第 N 层未生效"。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8ab0386f-d463-4134-962c-06a49850e3c1:1:63c17687833ef40e4d78
evidence_refs: learning:learn:52091399ced0
created_at: 2026-10-13T21:36:40.518410+08:00
updated_at: 2026-10-13T21:36:40.518410+08:00
---
## Trigger
被问"这个修好了吗/上线了吗"，且先前上下文已精确定位修复（文件+行号/语义）及可选加固点；结论需覆盖源码、提交、回归测试、构建产物与运行中服务多个层面，任一层脱节都会让"已修"变成误报。

## Discriminator
各层在当时各有一条机械真值可一次命中：修复位置已被点名（可直接读当前工作区文件）；提交包含关系可由 merge-base --is-ancestor 判定；产物包含可由 bundle 中修复的 minified 特征（如特定调用先后序）判定；运行层可由 live fetch 分发的 asset 判定。同时存在一条负判别：构建产物 mtime 早于修复 commit 不构成"未包含"证据（本地/工作区构建先于提交属正常），除非已知构建只从已提交 revision 产生。

## Short path
- 直接读被点名文件的点名行（当前工作区路径）得出源码层结论；若文件名搜索首批命中全为 .releases/ 快照副本，立即改走当前路径而非枚举快照
- 定向核回归测试与后端加固：按测试名/关键 warn 文案 grep，一次定位
- 取运行服务 HEAD，git merge-base --is-ancestor <fix_commit> <deployed_head> 判包含
- 对部署/当前 dist bundle 直接 grep 修复的 minified 特征，并核对相对顺序与源码修复结构一致（如清除在 guard 之前）；发现 mtime 早于 commit 时不据此下结论，只信字节
- runtime manifest 缺产物哈希即跳过，直接 fetch 运行服务页面/JS，确认分发的 bundle 即含修复特征的那个
- 分层报告结论并附残余事项（客户端缓存需 F5、遗留孤儿 run 另行处理）

## Stop conditions
- 源码即无修复 → 立即答"未修"，不再核验下游层
- 某层确定性失败（部署 HEAD 不含 fix commit，或分发 bundle 无修复特征）→ 报"第 N 层未生效"并停止
- live 分发 bundle 已确认含修复特征 → 停止核验，仅附客户端缓存提示

## Verification
- bundle 中 minified 特征的相对顺序与源码修复结构语义一致
- merge-base --is-ancestor 退出码为 0
- live fetch 得到的 asset 文件名/内容 == 含修复特征的 bundle

## Counterexamples
- 已知构建管线只从已提交 revision 构建（如 CI）时，产物时间早于修复提交确为"未包含"的有效证据——判别事实变为构建输入源而非一律看字节
- 后端/配置类修复无前端 bundle：以运行时生效值、行为或日志为准，跳过 bundle 层
- dev server/HMR 直跑源码：源码层≈线上层，省略祖先/dist/fetch 各层
- CDN 或中间缓存遮挡分发链：live fetch 见到修复不等于用户端已生效，结论必须附带缓存刷新提示
