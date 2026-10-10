---
method_id: foreign-namespace-reference-pivot-to-identifier-keyed-ledger-7e3191d702c8
name: foreign-namespace-reference-pivot-to-identifier-keyed-ledger
description: 当上游消息引用的证据文档位于外部命名空间（如对方 agent 的 sandbox:/ URI，拼进本机路径必然不存在），且消息正文已内联带唯一标识的具体事实时，不要继续定位或换词搜索那份拿不到的文档；把消息内的标识符（缺陷编号、数值症状、提交特征）当作查询键，直接检索本地权威账本（git log/commit message/代码标签），再沿 diff 点名的符号定位机制。文档引用只作为'内容已内联'的注脚，不作为行动前提。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:18e51b8e-580f-47b5-a867-ad21b62684b1:568:fec872b5191b3639993c
evidence_refs: learning:learn:03cd59ea34ca
created_at: 2026-10-08T19:57:11.588907+08:00
updated_at: 2026-10-08T19:57:11.588907+08:00
---
## Trigger
上游消息引用一份证据文档，但引用形态表明它在外部命名空间（sandbox:/workspace/scratch/<hash>/... 拼接本机路径不可能命中），且正文已内联可操作的唯一标识与量化症状（如 BUG-13b timeout=30→120/93、BUG-07 拨号 1234/状态 7777）；对该路径的首次 read 已失败且回执确认不存在。

## Discriminator
当时已可见两条事实：①引用 scheme 为 sandbox:——这是报告方自己沙箱里的 artifact，本工作区的 search_files/search_evidence 对它结构性无命中；②消息正文已写明两个缺口的事实并给出行动指向（'建议先追补这两项'），所需未知量只剩'对应本地哪些提交/代码'，这一跳应由标识符查 git log 完成，而非继续找文档。

## Short path
- 解析消息：任务=追补 BUG-13b/BUG-07；未知量=两项在本仓库的对应提交与代码通路。
- 首次 read 沙箱路径失败且回执确认后，依 sandbox: scheme 判定 artifact 在外部命名空间，立即停止对该文件的定位类搜索（不再 search_files/search_evidence 换词枚举）。
- 以消息标识符查本地账本：git log 匹配 BUG-13b/BUG-07/ASSESS-20261008 → 锁定对应提交（b8553384c、077eca97b）。
- 读提交 message/diff——其本身已写明机制（13b: env_int 拒 '0.5' 静默回退 120；BUG-07: 状态展示 registry 路由声明而非实际拨号目标）。
- 沿 diff 点名的符号窄查（providers.py 的 provider 级 timeout_s 解析、resolver.py 的 TomlField 投影、client_params/llama-server 发现回退），定位 mapping 丢参与 1234 回退的精确分支。
- 本地复现两项缺口并验证，通过后修复汇报；每条结论以本地命令输出为据。

## Stop conditions
- 已用消息标识符在 git/代码中定位对应提交，并读到与其症状一致的机制解释。
- git log 与代码标签均无该标识符的任何匹配——pivot 无效，转而向用户索要 artifact 导出或请其内联证据。
- 消息正文已含全部所需事实且无需代码侧核实（仅询问事实而非要求修复）时，直接行动，不查账本。

## Verification
- 对'缺口仍复现/已修复'的每条结论，须有本地复现命令或测试输出支撑，不以外来消息文本为终证。
- 核对 timeout 的全部解析通路（provider 级 timeout_s / 全局 LLM_TIMEOUT_S / resolver TomlField 投影）与 BUG-07 的发现失败回退分支，确认与提交 diff 描述机制一致后才落修复。

## Counterexamples
- 引用文档位于本工作区或共享挂载路径（无外部 scheme）：必须直接读——文档可能含消息未内联的验收细节与证据，跳过会漏验收条件。
- 消息无具体标识符（无编号、无数值症状、无提交线索）：没有可查键，应请用户导出 artifact 或内联内容，而非盲查本地账本。
- 仓库无按缺陷编号打标签的惯例（commit message 与代码注释均不含该 ID）：git 检索查不到对应项，pivot 失效。
- 消息内联事实可能过期或与代码矛盾：pivot 只替代'找文档'这一步，替代不了本地复现验证。
