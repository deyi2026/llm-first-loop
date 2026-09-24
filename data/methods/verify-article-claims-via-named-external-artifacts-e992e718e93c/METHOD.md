---
method_id: verify-article-claims-via-named-external-artifacts-e992e718e93c
name: verify-article-claims-via-named-external-artifacts
description: 当用户只给文章链接且文章声称某软件、插件、版本或官方关系时，先从正文抽取具体外部标识（包名、安装命令、仓库/组织、版本号），直接查询对应权威登记处或源码仓库，再逐条比对；不要先做本地文档或文件枚举。只有外部标识缺失或权威源不可达时才扩大搜索。
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:6aec21cb-8703-4ef8-9229-f57e73cdb86e:3:1c57e6fae8908e06d3ae
evidence_refs: learning:learn:d7388af76a21
created_at: 2026-09-24T00:22:41.604088+00:00
updated_at: 2026-09-24T00:22:41.604088+00:00
---
## Trigger
用户粘贴文章或网页链接但未给明确指令，正文包含关于外部软件包、插件、版本、仓库或官方归属的事实性说法。

## Discriminator
正文已出现可操作的外部标识或因果边：安装命令、包名、仓库/组织名、版本号、文档路径；这些标识直接指向权威登记处或源码仓库，而本地语料没有任务相关线索。

## Short path
- 读取起始文章，判断需要核实的是外部存在性、版本、归属还是正文观点
- 从正文抽取具体外部标识：包名、安装命令、仓库/组织、版本号、官方或非官方说法
- 按标识直接查询对应权威源：包登记处、源码仓库、发布记录；优先查 dist-tags、releases 等可验证字段
- 将文章每条硬事实与权威回执逐项对齐，区分已证实、未证实、误读
- 若关键事实已证实或明确标记未证实，停止发现并输出结论

## Stop conditions
- 文章关键事实已由对应权威源回执证实或证伪
- 外部标识不足且已尝试合理权威源仍无法定位
- 继续查询只会增加重复抓取而不改变结论

## Verification
- 最终结论中的每个硬事实都标注对应权威回执来源
- 包版本使用登记处 dist-tags 或发布记录，而非 README 叙述
- 官方或非官方归属使用仓库 owner、license、created_at 等元数据

## Counterexamples
- 任务目标是本地代码库或离线文档中的事实，应查本地文件而非外部登记处
- 文章只是观点或评论，没有可核实的外部存在性、版本或归属声明
- 正文给出的包名或仓库名明显是示例或占位符，直接查询会产生错误候选
