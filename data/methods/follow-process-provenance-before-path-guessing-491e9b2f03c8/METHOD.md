---
method_id: follow-process-provenance-before-path-guessing-491e9b2f03c8
name: follow-process-provenance-before-path-guessing
description: 定位'管理某个在线服务的工件（脚本/配置/基线工具）'时，先用该服务自身的 provenance——属主进程完整命令行、launchd/服务标签、相邻控制脚本——确定真实用户目录与项目根，再做目录级列举；把权威'路径不存在（TTL 登记）'回执当作切换发现机制的信号，而不是继续枚举兄弟路径或全树关键词 grep。本集最早摩擦：健康检查输出尾部已含 llama-server 完整命令行（/Users/<real-user>/Project/research/...），却先猜 /Users/<guess>、/Users/<real-user>/Project 等路径，随后又全树递归 grep 指标名，命中大量无关 eval 浏览器缓存。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cba0dcfa-4656-4850-921d-1fad481ce73d:82:279dbfb3871267a1e72e
evidence_refs: learning:learn:b876ba8ec78d
created_at: 2026-09-20T17:19:17.174132+00:00
updated_at: 2026-09-20T17:19:17.174132+00:00
---
## Trigger
需要定位与一个正在运行的服务相关的工件（管理脚本、指标定义、配置），路径未知；且早先工具输出已暴露过该服务进程的完整命令行、服务标签或同目录控制脚本名。

## Discriminator
先前输出中已可见属主进程完整命令行（含真实用户家目录与部署根，如 /Users/<real-user>/Project/research/<deploy>/build/bin/...）与服务标签/控制脚本名（如 *8901-control.sh、monitor 脚本、plist 名）；以及工具回执明确登记'该路径不存在（TTL 24h）→ 建议停止该路径搜索'。任一事实都足以把'文件系统任意位置'缩成'该部署所在目录'。

## Short path
- 查服务端点确认身份；同时从输出截取属主进程完整命令行与服务标签（未附带则按端口/进程名 ps 一次）。未知量：部署在哪、由哪些脚本管理。
- 沿命令行中的项目根与相邻控制脚本做一次目录列举（ls 该 runtime/部署目录）。未知量：目标工件（管理脚本、README）是哪一个文件。
- 仅在定位到的工件及其 README 内定向 grep 指标名（如 gen1）。未知量：该指标是存档历史值还是实时探针。
- 若为实时探针，且对相邻日志/评审文档做一次定向 grep 确认无存档数值，立即转为按工件源码中的同款探针定义重测，而不是继续翻历史或扩大搜索。未知量：当前真实数值。
- 数值产出且请求形状与工件内探针定义逐字段一致即停止，进入汇报/落盘。

## Stop conditions
- 工件已通过进程/服务标签 provenance 定位，且指标语义（存档值 vs 实时探针）已由工件源码或 README 判定
- 权威回执登记某路径不存在后，不再对其兄弟路径做同类猜测，发现机制已切换（进程 provenance / 定向 grep）
- 用户所需事实已由与探针定义一致的来源产出并验证，不再追加全目录/全树枚举

## Verification
- 定位到的路径与运行中进程命令行/服务标签同根、同用户（如都在 /Users/<real-user>/Project/research/ 下）
- 重测使用的请求形状（prompt、max_tokens、流式与否）与工件源码中的探针定义逐字段一致
- 回答所需事实取得后，回溯确认没有发生在 provenance 锚点命中之后的多余宽枚举

## Counterexamples
- 目标服务未运行或已下线：无进程 provenance 可用，目录索引/文件名搜索才是正确起点
- 要找的工件与任何运行中进程无关（如一份上月的历史报告、纯文档）：命令行 provenance 不构成指向
- 不存在回执可能过期（文件刚被创建）：对确切路径做一次廉价复查是合理的，不算扩散
- 容器/多主机环境：本机 ps 反映不了真正服务进程，provenance 边断裂，应换服务注册层发现
