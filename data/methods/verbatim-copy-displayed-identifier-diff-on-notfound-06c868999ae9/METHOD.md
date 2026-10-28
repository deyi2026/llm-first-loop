---
method_id: verbatim-copy-displayed-identifier-diff-on-notfound-06c868999ae9
name: verbatim-copy-displayed-identifier-diff-on-notfound
description: 当先前工具回执（搜索结果、目录列表）已逐字展示过目标路径/文件名/ID 时，后续读取必须逐字复制该串（日期、哈希等易错段程序化提取），而非凭记忆重建；若收到确定性 not-found（回执注明该路径已登记不存在、建议停止该路径），应先把本次尝试串与回执展示串做字符级 diff 定位转写差异，再按展示串重读一次；不要在未 diff 前用同一错误前缀换通配符重试，也不要先归因于编码/环境差异。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d1e343a5-0eb5-4b62-b607-a8cd333ed256:427:d882fd1bb1098e1ea1cf
evidence_refs: learning:learn:0f7e6a7ab334
created_at: 2026-10-15T11:38:26.584227+08:00
updated_at: 2026-10-15T11:38:26.584227+08:00
---
## Trigger
需要读取或引用一个此前工具输出中已出现过的精确路径/文件名/标识符；或一次读取因『文件不存在』确定性失败，且回执提示该路径已登记不存在、建议停止搜索。

## Discriminator
失败前已可见的两件事实：(1) 先前 ls/search 回执已逐字展示目标文件名（含精确日期段），且自己的计划文本也已正确引用该日期——说明失败是转写差异而非目标缺失；(2) 失败回执是确定性 not-found（带 TTL 登记与停止建议），而非超时/瞬时错误——这足以排除『环境编码问题』假设并收敛为『转写差异』假设。

## Short path
- 读取前：从展示该目标的回执中逐字复制路径，日期/哈希/长随机段不做手工转录
- 若确定性 not-found：将本次尝试串与回执展示串做字符级 diff，定位差异段（日期、连字符、扩展名），按展示串重读一次
- 若 diff 无差异或展示串本身也失效（目标被并发移动），才转 search_files 定位
- 禁止在未 diff 前用同一错误前缀换通配符重试，或无证据地归因编码/环境差异

## Stop conditions
- 已按回执展示的精确路径成功读取目标
- diff 证明展示串已失效，转入常规检索并由其停止条件接管

## Verification
- 成功读取的路径与先前回执展示串逐字一致（可机械比对）
- 每次对确定性 not-found 的重试前，能指出与上一次尝试的具体字符差异

## Counterexamples
- 目标路径从未在任何回执中展示过：无 diff 对象，直接定向检索
- 失败是 transient（超时/5xx/限流）：重试原路径即正确，diff 反而绕路
- 目录列表被截断且目标在未展示部分：展示串不可用，需分页或定向搜索
- 列表含多个副本（worktree 拷贝）：复制任一展示串可成功，但仍应先选定权威位置（仓库根）再读
