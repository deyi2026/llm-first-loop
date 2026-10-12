---
method_id: followup-questions-route-to-recent-artifact-first-4ef2b5c311a1
name: followup-questions-route-to-recent-artifact-first
description: 用户用代词或省略追问刚完成工作里的实体（如'需要和他交流吗'）时，答案载体通常是刚产出的 artifact（报告/附件/输出文件）：它同时装着'他是谁'与'可用渠道'。先用最近 provenance（最新 evidence 条目、已知输出路径、文件时间戳）定位并读取该 artifact，再对已抓取原始素材做定向 grep；不要先拿猜的关键词组合去语义搜索 evidence/memory——关键词猜不中只会连环空转，且搜回来的还是同一份 artifact 的二手碎片。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:55:bbc255ff3b0214da5e6d
evidence_refs: learning:learn:5b016dabd956
created_at: 2026-09-18T02:10:40.692924+00:00
updated_at: 2026-09-18T02:10:40.692924+00:00
---
## Trigger
用户追问以代词/省略主语指代先前任务中讨论过的实体或结论（'他''那个项目''过去交流一下'），且该任务在近期（同会话或最近 evidence 时间戳内）刚产出一份可定位的分析 artifact（报告/附件/输出文件）

## Discriminator
追问中的指代词本身 presuppose 先前共享上下文，且最近 evidence 条目/输出文件时间戳显示几分钟前刚完成并交付了一份分析（如 send_feishu_attachment、报告文件时间戳）——这两个在第一次检索前即已可见的事实，把'全 memory 关键词搜索'缩成'直接读最近那份 artifact'

## Short path
- 从追问的指代词识别未知量：'实体是谁 + 有哪些可用渠道'，并判断答案大概率在刚产出的 artifact 中
- 用最近 provenance 定位 artifact：查最新 evidence 条目或已知输出目录（ls 报告目录），不做关键词猜测
- 读取 artifact 主体，提取实体身份、关键结论与未决疑点清单
- 对已抓取的原始素材做定向模式 grep（邮箱/社区/合作/联系等）补齐 artifact 未直接组织的联系细节
- 按用途分叉给建议（核验 vs 合作），指出自述证据的结构性局限，并澄清代词歧义后停止

## Stop conditions
- artifact 已提供实体身份、可用渠道与关键限制，足以回答'值不值得/找谁/问什么'
- 指代无法从 artifact 或当前上下文消解时，直接向用户澄清，不再扩大 memory 搜索

## Verification
- 回答中每条渠道/事实可回指 artifact 或其原始素材的具体行/段落
- 工具序列中不存在针对 evidence/memory 的同源重复关键词试探，未出现'搜不到→换词→换源'链条
- 对时效敏感的渠道（服务在线状态等）已标注'需实测'而非当作 artifact 中的既成事实

## Counterexamples
- 追问内容超出先前 artifact 范围（新事实、新目标）——artifact 无答案，需新检索或实测，如'API 现在可达吗'不能靠读旧报告回答
- 纯对话上下文、没有任何已产出 artifact——语义 memory/evidence 搜索是合理起点而非绕路
- 目标信息易变（联系方式时效、服务在线状态、人员变动）——artifact 只提供渠道线索，当前有效性需另行核验
