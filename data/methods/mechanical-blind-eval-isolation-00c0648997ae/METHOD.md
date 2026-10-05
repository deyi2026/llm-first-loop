---
method_id: mechanical-blind-eval-isolation-00c0648997ae
name: mechanical-blind-eval-isolation
description: LLM 评分者对带答案的评测池评分时，通过"评分窗口内答案物理移出 + 隔离子代理 + sha 校验恢复"实现机械级盲评，而非仅靠指令承诺。适用于 agent 工作区内的一次性盲评/双盲裁决。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:abda90a9-c633-4664-b777-2ef993c8f7d9:649:1c308e6cb7880f6316d7
evidence_refs: evals/instrument_qualification_v1/iq_R1_notes.md,evidence://v1/12db7c7616060cc4a8f364d18c97d3e3dfb6c58db9f77b650943b231b2930451
freshness_refs: evals/instrument_qualification_v1/iq_R1_notes.md
created_at: 2026-10-05T23:28:36.104726+08:00
updated_at: 2026-10-05T23:28:36.104726+08:00
---
# 机械盲评隔离（LLM 评者物理盲化流程）

name: mechanical-blind-eval-isolation

## Trigger
需要 LLM 评者对一套带标签/答案的评测盲表独立评分，且评者与构造、分析环节同处一个 agent 工作区、共享文件系统；"评者看不到答案"目前只是任务文本里的指令级承诺，需要升级为机械级事实。

## Discriminator
- 存在含标签或答案的密封件（sealed/candidates/他评答卷/FORENSIC*）且与盲表同仓库；
- 评者可由隔离子代理承担（spawn_subagent：inherit=false、无网络、工具面可限 read_file）；
- 一次性裁决设计：双评均落盘并提交后才允许开封分析。
若答案本就公开或评者为不可隔离的外部人类，本方法不适用。

## Short path
- 逐一路径登记全部密封件 → `sha256sum` 生成基线清单
- 评分窗口开启：密封件物理 `mv` 出仓库根，移到仓库外同卷隔离目录（`.iqv1_quarantine_<ts>/`），`ls` 确认仓库内无残留
- 启动隔离子代理评分（fresh session；任务文本含冻结问句原文，只指定盲表一个文件）
- 评分结束：密封件原位 `mv` 回，`sha256sum -c` 全 OK 才算恢复成功；删除隔离目录
- 双评均落盘并 git commit 后才运行开封分析器
- 如实登记残余盲点（.worktrees/、私有归档内历史副本等）：残余风险降级为指令级盲，留痕不假装完美

## Stop conditions
- 密封件全部恢复且 sha256 -c 全 OK；
- 隔离目录已删除；
- 评者答卷落盘（必要时父会话逐字誊录，旁注记录权威原始 observation 的 sha256）；
- 偏离与残余盲点已写入评分旁注。以上四条缺一即流程未闭合。

## Verification
- 恢复校验：sha256sum -c 输出全 OK（机械校验，非目视）。
- 评者轨迹审计：子代理实际工具调用清单仅含盲表访问路径（IQ v1 实测 read_file×2 + read_evidence×8 分页，无答案文件访问）。
- 结果侧旁证：双盲成立时 R1×R2 一致性不因隔离失败被污染（IQ v1 κ=1.0，2026-10-05）。

## Counterexamples
- 只在任务文本写"不要看答案文件"而不物理隔离：指令级盲，子代理一次 search/read 即破盲，不可声明机械盲。
- 隔离清单遗漏未登记副本（.worktrees/ 等）：隔离对未登记路径无效，必须登记为残余盲点而非宣称完备。
- 密封件恢复后不做 sha 校验：无法排除移动过程损坏，后续开封分析的对象真值存疑。
- 评者无时钟时各行 ts 不可信：统一用 harness 指定字面值并在旁注记录实际窗口。
