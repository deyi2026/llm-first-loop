---
method_id: consume-miss-suggestions-before-requery-or-broad-sweep-67621e7ad7ab
name: consume-miss-suggestions-before-requery-or-broad-sweep
description: 当发现类工具（文档搜索/索引查询）返回未命中、但响应附带候选/最近列表时，把该列表视为已被收窄的候选集：将命名的条目解析为具体路径并直接读取，而不是改写关键词重查同一工具，或转向更宽的文件系统扫描。仅当建议与目标语义无关、无任何候选、或版本可疑时才扩大发现。避免在答案已由权威来源证实后再做确认性枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:1739:e55da4cf3a7bf8696f31
evidence_refs: learning:learn:22a758d8b6cd
created_at: 2026-09-19T07:43:13.891182+00:00
updated_at: 2026-09-19T07:43:13.891182+00:00
---
## Trigger
文档/索引搜索工具返回 miss，但响应中带有 suggestions、最近文档、相关条目等候选枚举，且其中出现与目标语义直接对应的命名条目（如正在找设计文档时，miss 响应已列出该设计文档与配套 qualification 文档的标题）。

## Discriminator
miss 响应附带的候选枚举中是否已精确命名了正在寻找的 artifact。若已命名，剩余未知量只有一个——把标题解析成实际文件路径；此时用不同关键词重查同一搜索工具不会产生新信息（第二次 miss 返回了与第一次完全相同的建议列表，即为其证）。

## Short path
- 对照 miss 响应附带的候选/最近列表与用户所需语义：是否已出现目标 artifact 的标题
- 若已命名：用一次目录列举（ls docs/ 或等效）把命名标题解析为具体文件名，不再重发同工具查询
- 直接读取解析出的文件，提取关键事实（范围、结论、基线/commit SHA）
- 若读出的基线 SHA 与运行时/部署 SHA 不一致：用单次针对性 VCS 查询（git log/status 证实包含或祖先关系）闭合 lineage，不扩散到代码扫描
- 所需事实全部由权威来源（部署回执、文档、git 输出）证实后停止；跳过事后 glob/宽搜索等确认性枚举

## Stop conditions
- 目标文档已从建议命名条目读取且内容回答了用户的验证问题
- 文档引用的基线 SHA 与当前部署 SHA 的关系已被一次 VCS 查询证实（包含/祖先）
- 部署/健康状态直接来自回执与端口探测字段（pid 一致、matches_desired_generation、HTTP 有响应），不再追加探测

## Verification
- 读取的文件标题与建议列表命名一致，且日期/版本字段表明非过期同名文档
- 文档中引用的 SHA 经 git 输出证实被当前运行 HEAD 包含
- 进程健康证据链闭环：监听端口的 pid 与部署回执 pid 一致

## Counterexamples
- 建议列表只是热门/最近推荐且与目标语义无关（类似 analytics），此时应改用更具区分度的关键词重查
- miss 无任何附带候选且无目录列表可解析时，broad discovery（glob/全目录扫描）才是正确下一步
- 存在同名多版本文档且标题无法判别新旧时，需先核日期/基线 SHA 再采信建议条目
- 候选列表过大且标题模糊时，标题解析相比关键词检索无明显收益
