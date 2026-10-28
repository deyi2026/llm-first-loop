---
method_id: ground-derived-label-claims-in-semantics-and-existence-probe-39d27fc2e645
name: ground-derived-label-claims-in-semantics-and-existence-probe
description: 把系统派生状态标签（changed/missing/unbaselined/not_tracked）翻译成关于实物的断言（删了？移了？存在？）之前，先用两步定案：(1) grep 标签字符串读计算源码里的状态机形式语义——词表互斥，若设有 missing 态，则 changed 只在『实物存在但哈希≠基线』时出现，标签名本身已回答去向问题；(2) 对每条 ref 在绑定根下做一次直接探针（test -f / 现算哈希比基线）。摘要视图里 current=<none> 是展示层缺省，不是文件系统事实。本集以此推翻上一轮『文件被删/移动』误断言：实测两文件均在、哈希≠基线，changed=内容演进。附带纪律：对必然存在的字符串 grep 为空时先怀疑引用路径不存在（假阴性），定位真实模块后再引用；处置建议只提状态机实际允许的转移。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:39:e4895479e68eebf848a4
evidence_refs: learning:learn:87b65fba62b7
created_at: 2026-10-17T23:19:35.161454+08:00
updated_at: 2026-10-17T23:19:35.161454+08:00
---
## Trigger
状态/健康视图给被跟踪 artifacts 打了派生标签（changed/missing/unbaselined/not_tracked 等），任务要求把标签转成关于实物的可核验断言（删了/移了/存在/可读）或处置决定（删除/退役），且标签由仓库内可读源码计算

## Discriminator
标签词表互斥且语义可从计算源码读到：状态机若设有 missing 态，changed 仅在『文件存在且现哈希≠基线』时出现——标签名已回答『是否删除』；且每条 ref 一次直接探针（存在性/哈希）即可定案。摘要视图的 current=<none> 是渲染缺省，不是文件系统事实；对『必然存在的源码字符串』grep 全空通常是路径错误的假阴性信号。

## Short path
- 先 grep 标签字符串定位计算源码，读状态机形式语义：每个标签对实物意味着什么（changed 与 missing 的互斥定义）
- 对每条被断言的 ref 在绑定根下做一次存在性/同一性探针（ls/test -f；有基线则现算哈希对比）
- 只按探针回执出断言：EXISTS 且哈希≠基线 ⇒ 『基线后内容演进』，禁止推出『删除/移动』
- 处置类问题（是否删除/退役）先查 store 的转移面与证据要求，只提状态机允许且证据满足的选项
- 引用源码路径/行号前先确认路径存在：grep 为空且字符串必然存在时，先 ls/find 定位真实模块再引用

## Stop conditions
- 交付物中每条实物断言都有探针回执（存在性/哈希）或状态机源码定义支撑
- 处置建议只引用 store 实际支持的状态转移，无凭日常语义编造的入口或语义
- 引用的每条源码路径已经 ls/find 实际命中

## Verification
- 复算一致性：文件 EXISTS + 现哈希≠基线哈希 ⇒ 与 changed 标签闭环，断言成立
- 对照已读的状态机代码行核对每条标签解释（如 changed=hash不等、missing=文件缺失）
- 抽样复跑存在性探针确认绑定根正确（code_root 与 git_common_root 区分）

## Counterexamples
- 标签计算源码不可读（闭源系统/远端服务）：只能依文档+探针，并把标签语义标注为未验证，不读码
- 非文件型 ref（如 evidence:// URI）：test -f 不适用，须走该类型自己的解析/hydration 通道
- 渲染契约明确把 current=<none> 定义为『实物不存在』的系统：展示缺省即事实，判别器变为读契约而非探针
- 只需人口级统计、不做逐条实物断言的快速分诊：无需逐 ref 探针，避免过度取证
