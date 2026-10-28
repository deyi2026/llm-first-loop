---
method_id: late-stage-failure-reuse-receipt-stdout-then-symmetric-compare-a2f037e33df4
name: late-stage-failure-reuse-receipt-stdout-then-symmetric-compare
description: 『取数＋内联机械比对』的复合命令在末段失败（shell 语法错/diff 脚本 bug）但回执 stdout 已含完整权威数据（如完整 ls-remote 清单）时：判定取数已成功，不重跑整条管线，只把纯本地比对段拆出来单独重试；比对两侧必须对称归一（同排序、同过滤，符号 ref 如 HEAD 单独核验），并只用可移植 shell 构造（不用进程替换）。机械 DIFF 报差异、而人工逐行已见一致时，hunk 里纯次序/符号 ref 差异本身就是归一不对称的证据，修比对而非重取数。
aliases: 命令失败但输出都在要不要重跑, shell 比对段报语法错, diff 假差异是排序没对齐, bin/sh 不支持进程替换, HEAD 符号 ref 混进 diff 报不同
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e94a43-6a8f-4f61-aa24-5148726fbcda:59:d6b5731c326ab6ad7be5
evidence_refs: learning:learn:4cc2f8155fa6
created_at: 2026-10-24T17:32:35.206870+08:00
updated_at: 2026-10-24T17:32:35.206870+08:00
---
## Trigger
复合验证命令（数据获取＋内联 diff/sort 比对）以非零退出码失败，但回执 stdout 中目标清单已完整出现；或机械比对报 DIFF 而人工逐行核对内容一致

## Discriminator
三点当时即可见的事实：① stderr 把失败定位在管线末段（比对/排序/语法），而非获取段；② stdout 已覆盖全部预期条目并终止（末条目在、计数齐）；③ 错误信息暴露实际 shell 方言（如 /bin/sh → 不支持进程替换）。三者合力把『整条重跑』缩成『只重做本地比对，且用可移植＋对称归一的写法』

## Short path
- 收到非零退出码先判失败段：回执 stdout 清单是否完整、已终止、计数与预期相符
- 数据已完整则拆出纯本地比对步骤单独执行，不再把获取与比对耦合进同一条命令
- 比对用可移植构造（两侧各自 sort 成临时文件再 diff），归一对称：同排序、同过滤规则，符号 ref（HEAD）单独核验、不混入集合
- 若仍报 DIFF：先读 hunk——差异仅为行序不同或符号 ref 多/缺，即构成归一 bug 的证据，修比对逻辑后重跑一次
- diff exit=0 且逐项 SHA、侧计数与基准一致 → 核验完成，存档并汇报

## Stop conditions
- 对称归一后的机械比对 exit=0，逐项 SHA 与两侧 ref 计数（排除符号 ref）均与基准一致
- 回执数据不完整或失败发生在获取段（认证/网络/截断）→ 转入重跑获取，本方法不适用

## Verification
- 两侧经相同排序后 diff exit=0；非符号 ref 计数与基准条数吻合
- HEAD 等符号 ref 单独核验且指向预期的分支 SHA

## Counterexamples
- 失败发生在获取段（ls-remote 认证失败、网络错误、输出被截断）→ 回执不含完整数据，必须重跑获取而非比对
- 数据集大（数百条 ref）：模型内逐行比对易错，机械 diff 必要，但首次就应对称归一，不能先跑不对称版再修
- 环境已确认为 bash（先前回执成功执行过进程替换）→ 内联进程替换不是 bug，拆分动机不成立
- DIFF 后尚未逐行人工核对 → 不能直接断定『脚本 bug』，须先读 hunk 确认差异纯属次序/符号 ref 才修比对
