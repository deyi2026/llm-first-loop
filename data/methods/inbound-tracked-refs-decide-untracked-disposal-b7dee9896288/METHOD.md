---
method_id: inbound-tracked-refs-decide-untracked-disposal-b7dee9896288
name: inbound-tracked-refs-decide-untracked-disposal
description: 清理/处置指令指向一组已知精确路径的未入库工作区产物时，破坏性分支（删除）不得由产物自身信号（untracked、mtime、『非主线』直觉）触发。第一个未知量应是『已入库内容是否引用这些路径』：对 tracked 树做一次作用域受限的 grep，并用 git ls-files 对照同类兄弟文件的入库状态。零入边才支持处置；存在入边而文件未入库，说明它是悬空引用的缺失指称，决策翻转为收编（定向测试+密钥扫描后零改动提交），并单独上报建议被推翻的证据位置与既有数据策略边界，不顺手改策略。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:f6f1dadc-64d2-4789-bbac-44b68f133442:1026:28a6e42348f09ed54d75
evidence_refs: learning:learn:6afadc1dd02c
created_at: 2026-10-20T07:32:39.876761+08:00
updated_at: 2026-10-20T07:32:39.876761+08:00
---
## Trigger
收到按此前建议执行的清理/处置指令（删除『实验产物』『临时文件』等），目标是一组已列出精确路径的 untracked/ignored 工作区文件，且原建议带有尚未验证的可丢弃性条件（如『如果不是当前主线就删』）。

## Discriminator
两条当时即可获得的机械事实：① git ls-files 显示同目录同类兄弟文件已入库、而目标文件不在索引；② 对 tracked 树 grep 目标路径出现具体 file:line 引用（如已提交文档写明以这些文件为参数的运行命令）。二者同时成立 ⇒ 悬空引用而非孤儿；两查皆空才允许删除。untracked/mtime 只描述本地副本状态，不构成任何入边证据。

## Short path
- git status 拿到精确路径清单，把它们当作唯一检索键；不再对全库发起 search_files/全目录枚举
- 第一未知量=入边是否存在：对 tracked 树做 git grep（目标路径/basename）+ git ls-files 父目录看兄弟入库状态，一次命令定性
- 零入边且确认过期→按原指令处置；有入边且文件未入库→翻转为收编分支：先跑定向测试/selftest 与密钥扫描，代码零改动原样提交
- 向用户报告建议被证据推翻的位置（file:line 级引用），并把发现的政策级缺口（被 exclude 挡住的被引用数据输入）单独标记留待授权，不并入本次提交

## Stop conditions
- 每个目标产物的入边状态都已判定，并落到 处置/收编 二选一，无悬而未决项
- 收编分支：定向测试通过、密钥/敏感信息扫描通过、提交完成且 git status 干净
- 处置分支：删除后对 tracked 树 grep 目标路径零命中，无新增悬空引用
- 发现被引用的输入被 exclude 等既有策略挡在库外→停止并上报，不自行修改策略

## Verification
- 收编后 git ls-files <paths> 非空，且原先悬空的引用现在可解析到真实文件
- 已提交文档中点名的命令（定向 pytest、离线 selftest）实际执行通过
- 删除分支用同一 grep 复核 tracked 树零残留引用
- 最终向用户的报告包含支持反转的引用证据，而非仅口头改判

## Counterexamples
- 零入边的纯草稿、编辑器备份、发布快照副本→直接按指令删除，收编反而制造垃圾
- 引用只来自同批待处置文件自身（自引用簇），或来自同轮清理中也将被删除的文档→入边不会存活，不构成收编理由
- 被引用的是按数据策略刻意排除的大体积数据文件→入边存在也不意味着提交，应升级为策略决策而非绕过
- 用户已显式确认『删掉，引用下轮再修』→按用户明确指令执行，不再复核入边
