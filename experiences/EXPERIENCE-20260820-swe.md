---
title: SWE 批量流水线模式：调度后继续推进 + 本地验证即落盘 + 容器终验攒批并行 + 经验即时沉淀
scenario: SWE 多实例评测/任何批量任务（多实例修复、批量处理、多文件改动）
root_cause: "SWE 批量任务逐实例串行执行（每实例：环境→复现→修复→容器终验→等待）导致频繁停顿、轮次浪费；\"主循环只调度\"经验被误用在实例级粒度"
solution: "批量流水线五步：① 调度后台任务后立即继续下一个实例（RULE-AI-03 原文是\"所有待办均依赖外部事件\"才停——有可推进待办就继续）；② 本地验证（3.x py3.11 与容器 base 一致性已双重确认）通过即落盘 predictions jsonl，容器终验攒批统一并行（一个脚本 6 实例 docker run & wait，如 /tmp/swe_lfl_patches/batch10_verify.sh）；③ 镜像拉取批级串行（429 经验：manifest inspect 探测 + 串行 + 5s 间隔），不逐实例拉；④ 每实例修复模式立即追加经验文档（DecimalField 异常覆盖/db _cull 判空/FK base manager/DurationField sqlite 转换/attname pieces[-1] 等）；⑤ 卡住实例（静态 grep ≤3 次无果 → 运行时 debug ≤3 轮 → 仍无果标记待回访）不阻塞批量，攒批后统一回访。定位策略：静态 grep ≤3 次 → 切运行时 debug（打印 SQL/deconstruct，0.2s 级）→ 标记待回访。"
evidence: batch10 实测（2026-08-20）：7530/9296/12965/13023/13028/13109/13089/13121/13033 共 9/10 本地验证通过即落盘；攒批 6 实例并行容器终验（batch10_verify.sh）；13112 标记待回访不阻塞。对比：此前逐实例容器终验（3 实例 3 次等待）vs 攒批 1 次调度 6 并行
tags: [批量流水线, swe, 容器终验, 攒批, 经验沉淀]
source: {}
status: active
created_at: "2026-08-20T02:53:26.219003+08:00"
updated_at: "2026-08-20T02:53:26.219003+08:00"
---