---
method_id: known-long-installs-background-first-verify-via-receipt-path-ed0ef0e5f36a
name: known-long-installs-background-first-verify-via-receipt-path
description: 当计划本身已蕴含'必须下载新解释器/镜像/大量依赖'时（本集：本机仅 Python 3.14 且与 Terminal-Bench 兼容性存疑，自身决策用 uv 钉 3.12 → 必然触发托管解释器下载+全量依赖解析），不要用带短同步超时的前台命令试探。首次执行即发后台任务，等待期并行推进不依赖安装结果的子步骤（建 goal/任务图）；安装终态后读完整回执，取安装器自报的可执行目录（~/.local/bin）以显式 PATH 前缀做首次 CLI 验证，再经 --help 读真实子命令面后使用。本集将'前台 60s 超时→后台重跑→exit=127→再修 PATH'四步压缩为一次到位，消除重复安装与两类可预测失败。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b08a5a88-4c62-47f9-84ed-c3cb191c061d:83:5af43364095183bf3e04
evidence_refs: learning:learn:b2b04c432539
created_at: 2026-10-14T20:33:10.458306+08:00
updated_at: 2026-10-14T20:33:10.458306+08:00
---
## Trigger
即将执行的安装/拉取动作，其耗时结构可由已核事实预测为长：需下载未安装版本的托管解释器（如 uv tool install --python X.Y 且本机无该版本）、拉取未缓存镜像、或解析重依赖树；且执行通道存在同步超时上限（如 60s）。

## Discriminator
知识时点事实链：环境侦察已确认本机仅 Python 3.14、与目标工具兼容性存疑，且自己的方案就是'钉 3.12'——这一决策本身即证明安装必然包含解释器下载+依赖解析，几乎必超短超时；同时 uv tool 恒定安装到 ~/.local/bin 而非交互 shell 常缺该 PATH——首次验证应按安装回执自报路径拼显式 PATH，而非裸命令名重试或重装。

## Short path
- 环境侦察确认版本不匹配（Python 3.14 vs 工具兼容范围），形成'钉版本安装'计划，并据此预判长耗时结构
- 直接以后台任务发起安装（不做前台短超时试探），等待期并行完成建 goal/任务图等不依赖安装结果的步骤
- 安装终态后读完整输出：从回执提取 'Installed N executables' 与 bin 目录、以及任何 PATH 警告，以显式 PATH 前缀首次调用 CLI --version 验证
- 经 --help 读取真实子命令面后再执行具体子命令（不猜 'tasks list' 之类不存在的命令）
- 版本号、可执行路径、复跑命令落盘，进入下一阶段（小子集冒烟）

## Stop conditions
- 安装器回执报真实错误（依赖解析失败/网络错误，非超时）→ 转入单变量根因修复，不盲目重试
- 显式 PATH 下 CLI --version/--help 正常返回 → 安装阶段结束，禁止继续重装或换版本枚举
- 小子集冒烟跑通即证明工具链可用，停止环境层探索

## Verification
- 后台任务 exit=0 且输出含 'Installed N executables' 行
- PATH="<回执自报bin目录>:$PATH" <cli> --version 返回版本号
- 首次真实子命令（--help 或最小用例）执行成功，无 command not found

## Counterexamples
- 依赖与解释器已被 uv/镜像缓存预热（此前装过同版本）→ 前台数秒即完成，后台化反而引入等待-轮询开销
- 一次性小工具安装（brew 已缓存 bottle、单文件 CLI）→ 直接前台执行即可
- 执行环境不提供后台任务机制 → '后台优先'腿不适用，只能分片执行或调大超时，但'按回执自报路径做首次验证'腿仍然适用
