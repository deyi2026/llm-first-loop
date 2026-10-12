---
method_id: name-keyed-git-ref-lookup-before-enumeration-398f57241d7f
name: name-keyed-git-ref-lookup-before-enumeration
description: 执行“按建议执行”类任务且建议中已点名具体仓库工件（协议、fixture、eval ID）时：先用一次按名键控的 git 树查询（对权威 ref 做 ls-tree+grep）同时定位全部被引用工件，再从该 ref 读 blob 内容，并用一次 worktree 占用检查确定安全写入点（专用 worktree），然后才动笔。跳过知识/文档面的主题搜索与重复的宽泛 worktree/目录枚举，把“在哪、内容是什么、往哪提交”三个未知量压成一键一查。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:217:46ae093b890c01698ac0
evidence_refs: learning:learn:ef280848eb61
created_at: 2026-09-17T22:58:22.336597+00:00
updated_at: 2026-09-17T22:58:22.336597+00:00
---
## Trigger
任务或被执行的建议中出现文件名形状的具体工件标识（协议/fixture/eval/config 名称），且当前处于多 worktree 的 git 仓库、现有检出带未提交改动。

## Discriminator
进入枚举前已可见：待找对象的名字 token 已在请求中（可直接作 grep 键），且 git status 显示此类工件以 tracked 文件形式存在于树中——因此定位、取权威内容、定写入点都可由键控检索加单次占用检查解决，无需先做主题搜索或结构性枚举。

## Short path
- git status/branch 建立仓库与检出上下文，确认权威 ref 与脏检出状态。
- 用任务中已有的名字 token 做一次键控查询：`git ls-tree -r <权威ref> --name-only | grep -iE <tokens>`（需要谱系时附带最近触达 commit），一次解析全部被引用工件的位置。
- 从该 ref 直接 `git show <ref>:<path>` 读取每份权威内容（协议、计划、fixture 源码、复用契约），不读脏工作树。
- 单次 `git worktree list` 确认目标 ref 未被任何检出占用；为新建工件创建专用 worktree。
- 落盘并在目标 ref 提交；确认其他检出未受影响后停止。

## Stop conditions
- 全部被引用工件均已从钉定 ref 读取，仓内已冻结契约不再二次推导；
- 目标 ref 占用状态已确认且写入点已定；
- 新工件已提交到预期 ref，原有检出保持原样。

## Verification
- 新工件与已读 ref 内容是引用/派生关系，未重复推导已冻结契约；
- 提交落在预期 ref，`git worktree list` 与原检出 status 无意外变化；
- 同一未知量（位置/占用/内容）没有被第二次同类枚举调用重复回答。

## Counterexamples
- 要找的是主题或政策类知识而非命名文件——没有可用名字键，应先走 docs/知识面检索；
- 目标内容只存在于未跟踪的工作区文件或其他机器——对 ref 做 ls-tree 会漏，需直接检查工作树；
- 名字未知或过于泛化（如“那个报告”）——键控 grep 会洪泛或落空，需目录级浏览/发现；
- 仓库小而扁平——一次列目录已是最短路径，本方法不缩短任何东西。
