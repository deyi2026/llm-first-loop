---
method_id: exclude-masked-closeout-manifest-driven-add-f-and-tracking-verify-8fdebf9afa52
name: exclude-masked-closeout-manifest-driven-add-f-and-tracking-verify
description: 当本地 exclude/gitignore 遮蔽了必须入库的知识资产目录时，git status 的未跟踪清单不是候选全集：候选集改由在手的备份清单/回执构成；逐文件按内容裁定备份版与工作树版（超集/锚点节优先，不整包覆盖）；被遮蔽条目用 add -f；提交前用 git diff --cached --stat 核对暂存集精确、无并行会话文件混入；提交后用 ls-files/git log 验证跟踪而非再看 status；共享 exclude 配置不擅自改，登记人工裁决。
aliases: exclude把新文件藏住了怎么提交, git status 看不见的未跟踪文件入库, add -f 破除本地排除规则, 提交前核对暂存集别夹带并行改动, 备份版和工作树版不一致选哪个, 收口提交后怎么确认文件真被版本保护
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9982762e-d202-481b-9ca3-178124e943de:4365:64584dba60f80d5badb5
evidence_refs: learning:learn:5f22a8c01e78
created_at: 2026-10-26T07:29:14.189489+08:00
updated_at: 2026-10-26T07:29:14.189489+08:00
---
## Trigger
收口/入库任务发生在启用了 .git/info/exclude 或 ignore 规则、且这些规则遮蔽了必须获得 git 版本保护的资产目录的仓库；同时常有并行会话在同一工作树留下脏文件。

## Discriminator
status 回执里的 exclude 段落本身证明未跟踪清单被遮蔽：目标资产既不在 M 列表也不在 ?? 列表，但备份清单/早前回执已点名它们确实存在。因此候选全集必须来自在手的资产清单而非 status；且每个『已保护』断言只能用 ls-files/git log 的跟踪查询验证，status 永远给不出这个答案。

## Short path
- 一条基线命令同时取 status、exclude 规则段、备份/资产清单：未知量是『哪些资产缺版本保护、哪些被遮蔽』
- 若存在『写通道被封』的历史报告，先一次最廉价写探针定通道——封锁证据是通道作用域的，授权提权不等于当前通道被封；探针通过则走正常通道（最小权限），不消费提权
- 逐文件 diff 备份版 vs 工作树版：内容超集/含最新记录者胜，锚点节命中者为目标版；只回拷备份胜出的文件，不整包覆盖
- 普通文件 git add，被 exclude 遮蔽条目 git add -f；随后 git diff --cached --stat 核对暂存集精确等于预期清单，零并行会话文件混入
- 提交后用 git ls-files 与 git log -- <file> 验证每个资产已跟踪且落在收口提交；剩余脏文件逐一归属并行会话
- exclude 遮蔽的系统性风险不擅自改共享配置，登记为演进建议交人工裁决

## Stop conditions
- 全部目标资产在收口提交中被 ls-files 确认跟踪
- 剩余未提交文件已逐一归属为并行会话/其他任务所有，零误伤
- exclude 遮蔽风险已登记给人工，不留隐性裸奔

## Verification
- git diff --cached --stat 的文件数与名单精确等于预期清单
- git ls-files 过滤目标资产全命中；git log -- <文件> 显示收口提交
- 提交后 status 剩余项逐一指认归属，无一属于本任务遗漏

## Counterexamples
- 仓库没有 exclude/ignore 遮蔽：status 的未跟踪清单就是候选全集，add -f 反而危险，可能提交 ignore 故意挡住的密钥/.env/大产物
- exclude 是架构设计（如『运行时 store 唯一权威』）：add -f 入库可能违反设计意图，正确动作是先向配置所有者确认遮蔽是否应修改
- 备份与工作树是语义性分叉而非超集关系（双方各有独有且冲突的记录）：不能按超集裁定，需记录级合并或人工裁决
