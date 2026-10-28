---
method_id: manifest-verify-fetched-artifact-before-consume-4aa016596e58
name: manifest-verify-fetched-artifact-before-consume
description: 后台长任务抓取的多文件工件（模型分片/数据集/离线包）在加载或消费前，把『完成』当作可由工件自带清单在文件系统层一步验证的事实，而不是从管道截断的输出、被管道吞掉的退出码或作业沉默中推断；对外汇报的体积/分片数同样以盘上 stat 为准。一次确定性比对替代『误判完成→带病消费→发现残缺→重跑续传』的整轮返工。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d643a7c4-20a9-438d-a61f-dd25be27bf55:66:f0b6781558348881d14a
evidence_refs: learning:learn:07c6a0b139d0
created_at: 2026-10-16T20:45:45.565622+08:00
updated_at: 2026-10-16T20:45:45.565622+08:00
---
## Trigger
启动了长时间后台抓取/下载多文件工件（模型权重分片、数据集、镜像包），作业输出经过了管道处理或退出码不可信，且下一步要加载/评测/消费该工件时

## Discriminator
工件家族自带可枚举清单：本集在下载前就已看到同类模型目录含 model.safetensors.index.json（weight_map 列出全部分片），证明完成度可在文件系统层一步判定；同时 `hf download ... | tail -5` 的退出码属于 tail 而非下载器，这一事实在构造命令时已知

## Short path
- 发起后台抓取时不做破坏性管道：日志重定向到文件，或 set -o pipefail，保住下载器真实退出码
- 作业报完成后、消费前：解析工件自带清单（index 的 weight_map / checksums / 文件列表），与盘上文件数和大小逐项比对
- 有缺项→只续传缺失部分并回到比对步骤；全部命中→才加载/评测
- 对外汇报工件体积、分片数一律取自盘上 stat/清单，不用事前假设值（本集曾把 18GB 实物说成 29.5GB）

## Stop conditions
- 清单全部条目均在盘且大小与元数据一致（或 checksum 通过）
- 抓取工具返回未管道化的校验通过回执且退出码为 0

## Verification
- 盘上分片数等于 index/manifest 条目数，总大小与元数据相符
- 未管道化日志显示下载器自身退出码 0，而非管道末端命令的退出码
- 消费端（server/benchmark）加载无缺分片报错后才输出结论

## Counterexamples
- 单文件下载且工具自带 checksum 校验回执、退出码未被管道污染——直接信回执即可，清单比对是多余开销
- 流式/追加型产物没有可枚举清单——应改用大小稳定或生产者状态判断，本方法不适用
- 消费步骤对残缺工件会廉价且响亮地失败、重试代价极小——可先试后验（但大权重加载不属此类）
