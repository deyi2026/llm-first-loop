---
method_id: dangling-inline-ref-resolve-by-ls-before-history-queries-ab52825a91a0
name: dangling-inline-ref-resolve-by-ls-before-history-queries
description: 工件头注释写着『见 scripts/xxx.sh』这类同伴文件引用、需要判断指引是否可照做并给整改建议时，第一未知量是该路径在当前权威树里是否存在——一条 ls/test 即可闭合。『它是否曾经存在过』是另一个不改变任何整改选项的未知量，默认不付代价（大历史/含快照目录的仓库跑仓库级历史查询极易卡死）；确需历史时只用单路径有界查询，且同类查询超时一次后不得重发，改记『历史未知』收尾。
aliases: 注释里让看的文件不存在, 引用的脚本找不到怎么核实, 翻提交历史卡死还要不要重试, 安装说明指向缺失文件, 要不要查文件是不是被删过
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:561:7433cf560604ec7bd3cd
evidence_refs: learning:learn:8e6848341443
created_at: 2026-11-10T07:11:03.284511+08:00
updated_at: 2026-11-10T07:11:03.284511+08:00
---
## Trigger
审计或复核仓库工件（hook 头注释、README、配置文件）中『见 <相对路径>』式同伴文件引用是否可照做，或要在『补文件 vs 改指引』之间给建议时；尤其在历史庞大、含 .releases 类快照目录、仓库级历史查询曾超时的仓库。

## Discriminator
待裁决的动作（修引用、补文件、交用户定边界）只依赖『当前树中是否存在』这一现在时事实；工件头部已显式给出完整相对路径，一次目录列举即可裁决；『是否曾经存在、何时被删』对任何候选方案都没有区分力。若方案真依赖删除意图，才升级到单路径历史查询。

## Short path
- 从工件头注释提取被引用的完整相对路径（显式 provenance edge）
- 在当前权威树做一次存在性检查：ls <目录> / test -f <路径>；若裁决对象是特定 ref，用 git cat-file -e <ref>:<路径>
- 不存在 → 判定悬空引用，直接给出『补文件/改指引/交用户定边界』方案，并把『是否曾存在』显式标注为未核、不阻塞结论
- 仅当整改方案确实依赖删除时间或意图时，才跑单路径有界查询（git log --follow -- <路径>）
- 该类历史查询超时一次 → 不重发同类命令，降级回现在时事实并收尾

## Stop conditions
- 当前树存在性已定、整改方案已明确，即停止追问历史
- 任一仓库级历史查询超时一次，即终止该分支，改走现在时检查或标注未核

## Verification
- 核对被引用字符串与实际检查路径逐字符一致，防止目录改名造成的假悬空
- 确认存在性检查运行在与该工件同一 toplevel（或同一 ref）的权威树，而非邻近镜像/快照目录

## Counterexamples
- 任务本身就是考古（该文件何时、被哪个提交删除）→ 单路径 git log --follow 才是第一步，仅 ls 不够
- 被引用文件是安装/构建期生成物、按设计不入库 → 应检查生成器/安装器是否存在，直接 ls 工作树会误判为悬空
- 裁决针对另一分支或远端状态 → 存在性须对那个 ref 用 cat-file -e 判定，工作区 ls 无效
