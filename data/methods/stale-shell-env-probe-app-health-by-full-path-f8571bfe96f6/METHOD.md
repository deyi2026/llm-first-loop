---
method_id: stale-shell-env-probe-app-health-by-full-path-f8571bfe96f6
name: stale-shell-env-probe-app-health-by-full-path
description: 把 PATH 等环境修复写入 rc 文件后要验证应用本体时，当前探针 shell（ssh 非交互 exec、旧会话）不会加载新 rc，且早前回执已实测裸命令 command not found——在同一 shell 再发裸名探针必然复现已知失败，易把『解析失败』误读成『应用坏了』。每个探针只测一个未知量：应用健康用完整路径调用验证；修复生效用全新登录 shell 解析验证。用已知的 shell 环境事实消除注定失败的探针轮次。
aliases: bashrc改了还是找不到命令, 全路径能跑命令名跑不了, ssh里怎么确认程序本身没坏, command not found但其实装好了, 远程终端环境变量没带上
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1321:2cea672453759c055d73
evidence_refs: learning:learn:3c6370170cd4
created_at: 2026-10-29T16:13:30.895159+08:00
updated_at: 2026-10-29T16:13:30.895159+08:00
---
## Trigger
已把 PATH/环境变量修复写入 rc 文件（.bashrc/.profile 等），下一步要验证目标命令或应用本身是否可用；而所用探针 shell（如 ssh 非交互 exec、已运行会话）在早前回执中已出现裸命令『未找到命令』

## Discriminator
同一 shell 的早前回执已显示裸名 command not found，且 rc 文件写入不会改变当前已运行/非交互 shell 的环境 ⇒ 此 shell 中裸名探针的结果已预定，与被测应用健康无关、零新信息；应用级未知量只能用完整路径调用隔离出来

## Short path
- 从早前回执锁定已知事实：当前 shell 缺该环境，不再用裸名探针重测解析，也不再沿用会连环失败的多个子命令变体
- 用绝对/完整路径调用用户实际使用的子命令（如 web 服务），一次探针只隔离『应用运行时健康』这一个未知量
- 持久化修复走独立通道验证：rc 文件已含 export 行 + 在新登录 shell（bash -lc 'command -v <name>'）中解析成功
- 完整路径探针出现应用自身运行时错误才进入应用级排障；否则输出『新开终端即生效』并停止

## Stop conditions
- 应用经完整路径调用产出自身运行证据（版本号、服务监听、HTTP 200），回执不含『未找到命令』
- 新登录 shell 能解析命令名且 rc 文件含持久化行
- 用户侧生效方式（新开终端/重登）已明确告知

## Verification
- 探针回执属于应用自身日志而非 shell 报错
- `bash -lc`（或对应登录 shell）的 command -v 返回安装路径
- rc 文件中同变量多次 export 时无顺序冲突或重复定义

## Counterexamples
- 待验证未知量是『用户新终端能否找到命令』（测修复而非测应用）时，正确通道恰是全新登录/交互 shell 里的裸名探针；完整路径探针对此零信息
- 当前 shell 已具备该环境（本轮已 export 或继承自已修复会话）时，裸名探针便宜且有效
- 应用行为依赖 argv[0]/自身命令名（自更新、自定位类 wrapper）时，应按用户原样在新登录 shell 中调用，而不是在已知坏环境里换任何调用形式
