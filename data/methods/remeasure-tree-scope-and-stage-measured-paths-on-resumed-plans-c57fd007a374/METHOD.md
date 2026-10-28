---
method_id: remeasure-tree-scope-and-stage-measured-paths-on-resumed-plans-c57fd007a374
name: remeasure-tree-scope-and-stage-measured-paths-on-resumed-plans
description: 跨轮/跨会话执行先前给出的操作性建议（提交、验证、推送）时，计划携带的范围数字（改动文件数、目标清单）只是上轮记忆的未核采样，而工作树是多会话共享的活表面：先用一条 quotepath 安全的 status/diff --name-only 实测当前改动集，与记忆对账并向用户显式报告差值；暂存只用实测路径列表，untracked 规模大时禁用全量暂存；动作是否触发审查闸从规则文本与 hooks 现场判定而非默认触发/默认豁免；'要不要重启生效'这类派生问题若手中回执已构成行为证据（新写入内容即时可检索），据此裁决，不再调查缓存机制。
aliases: 接着上轮计划干 先把文件重新数一遍, 凭印象报的文件数没核过, 几百个未跟踪文件 全量暂存会夹带, 跨会话接续提交 范围先实测再暂存, 卡片改完要不要重启 检索回执说了算, 中文文件名 status 输出转义乱码
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:3e24aff2-8af5-497f-882a-a249bcc66acd:187:79e6037408a2fe069c76
evidence_refs: learning:learn:522876fe313a
created_at: 2026-10-28T08:57:39.532676+08:00
updated_at: 2026-10-28T08:57:39.532676+08:00
---
## Trigger
用户以'按建议执行'类指令跨轮接续一份先前给出的操作性计划，且计划携带凭记忆给出的范围声称（改动文件数、目标清单），而目标仓库工作树由多会话共享、持续落入新未跟踪文件（数百级 untracked），任务起点 task state 读取失败或缺失。

## Discriminator
task state 缺失的回执本身证明计划内容只存在于上轮记忆；而 list_evidence 已显示指向目标文件的 edit_file 回执，工作树可用一条 git status 直接权威测量。记忆计数与实测不一致时（如 14 vs 16），以实测为准并显式报告差值——记忆是过期采样，不是真值。

## Short path
- task state 读取失败 ⇒ 计划细节只在上轮记忆；第一未知量=当前改动集实测：一条 git -c core.quotepath=false status --porcelain=v1 同时取计数与路径，避免中文路径转义后二次重跑；不要先去证据库按记忆措辞搜计划原文。
- 实测清单 vs 计划声称对账：不一致以实测为准，向用户显式报告差值及构成（如 N Method + M Experience + 1 docs）。
- 暂存只按实测路径列表（git diff --name-only -z | xargs -0 git add）；untracked 规模大时 add -A / add . 是确定性夹带事故源，禁用。
- 动作是否落闸从现场权威一次判定：规则文本作用域 + .git/hooks 实查（本地 commit vs push/发表/全量测试），既不默认触发也不默认豁免；受闸动作停在用户授权+有效审查回执之前。
- 批量改动存活验证可脚本化：逐文件 yaml.safe_load + 工作区 vs HEAD 键集 diff（lost=[] added=[]），并用检索面实测新文本可见。
- 派生问题（如'要不要重启使改动生效'）先查手中回执是否已构成行为证据：提交前新写入内容已出现在检索回执 ⇒ 服务现读磁盘，无需重启，也不再调查缓存机制。

## Stop conditions
- 实测范围已与计划对账（差异已向用户报告）、按实测路径完成本地提交、tracked 工作树清零。
- 批量文件的解析存活（frontmatter/键集）与检索可见性均经实测确认。
- push/发表/全量测试等受闸动作：无用户授权与有效审查回执前不执行。

## Verification
- 提交后 git status 中 tracked 修改清零，仅剩已知 untracked。
- 全部改动文件 yaml.safe_load 通过，且 HEAD↔工作区键集 diff 为空。
- 用新 description/卡名在检索面实测命中新文本。
- 闸豁免有三重现场依据：规则文本作用域原文、hooks 实查、相关条款原文，而非凭印象默认。

## Counterexamples
- 计划在本会话刚产出、无并发写入者且范围已由回执钉死：重测退化为一次干净度检查，全流程对账与逐路径暂存属冗余仪式。
- 目标不在 VCS 而在数据库/持久化 store：权威测量应换成该 store 的索引查询，照搬 git 命令无效。
- 树中 untracked 极少且无并发会话：全量暂存风险低，逐路径暂存可省。
- 派生问题无现成行为证据时，不能凭'大概率现读'跳过，须先做一次最小探针再裁决。
