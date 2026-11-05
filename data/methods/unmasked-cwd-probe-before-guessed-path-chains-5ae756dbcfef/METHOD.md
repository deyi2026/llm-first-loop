---
method_id: unmasked-cwd-probe-before-guessed-path-chains-5ae756dbcfef
name: unmasked-cwd-probe-before-guessed-path-chains
description: 会话起点要在本项目仓库里执行命令时，不要硬编码记忆里的绝对路径，更不要写 `cd <猜的路径> 2>/dev/null || cd ~` 这类把定位失败静默吞掉的兜底：兜底会让人在错误目录里继续跑，派生出 not a git repository / No such file 等看似多源的失败回执，实为同一根因的多个投影。第一步发一条不屏蔽 stderr 的 pwd 或 git rev-parse --show-toplevel，回执给出真实 home/仓库根，一次即可证实或证伪记忆路径；不一致时用仓库内唯一文件名做一次有界 find 定位真根，再执行实际动作，不换第二个绝对路径重猜。
aliases: 先 pwd 再拼路径, not a git repository 但命令本身没错, cd 猜路径 2>/dev/null 兜底吞错, 硬编码上次会话的项目绝对路径, 回执用户名和记忆路径对不上
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:27698664-7344-4a1d-8cd7-99256ecf501b:525:5e7bfab67577d7b096cb
evidence_refs: learning:learn:02baaf822de3
created_at: 2026-11-05T00:44:42.488431+08:00
updated_at: 2026-11-05T00:44:42.488431+08:00
---
## Trigger
新会话/新上下文起点，需要对某项目仓库执行命令（git/grep/读写文件），当前没有已验证的工作区路径，而命令中准备写入或已写入来自记忆/上次会话的绝对项目路径

## Discriminator
第一条命令回执里未屏蔽的 pwd/rev-parse 输出：真实 home 与仓库根一旦给出（如回执显示 /Users/<user> 而记忆路径是别的用户前缀），记忆路径立即被证实或证伪；masked 兜底后收到的一串 fatal: not a git repository + No such file 并不是多个独立故障，而是同一路径错误的多个投影

## Short path
- 发一条不带 2>/dev/null、不带 `|| cd ~` 兜底的 pwd（或 git rev-parse --show-toplevel），未知量：当前真实工作区根在哪
- 把回执根与记忆绝对路径比对：一致→直接执行实际命令；不一致→用任务已知的唯一文件/目录名做一次有界 find（限 maxdepth）定位真实仓库根
- 在已验证根内执行 git status/grep/read 等实际动作，命令里不再出现未经验证的记忆绝对路径
- 若唯一文件名 find 也未命中，停止换绝对路径重猜，改为列项目根候选目录或向用户要路径

## Stop conditions
- pwd/rev-parse 回执已落在目标仓库内，或唯一文件名 find 已命中真实根：定位完成，不再发探测命令
- 后续命令回执中的 cwd/路径前缀与探测结果一致，不再出现目录错位类失败

## Verification
- 抽查后续每条命令回执的 cwd/路径与第一步探测所得根一致
- 确认命令中不再残留吞掉 cd 失败的兜底结构（stderr 重定向 + || cd ~）
- 记忆路径被证伪时，所有实际动作均基于探测所得根执行

## Counterexamples
- 上一条工具回执已证明当前 cwd 就在目标仓库内：直接执行业务命令、从其回执顺带确认 cwd 即可，独立探测是冗余
- 目标绝对路径由用户消息或权威文档逐字给出且带 provenance：直接使用，不需要先 pwd
- 任务本身就是探索未知机器/未知目录结构：有界 find/ls 是主路径，pwd 只是前置一步而非判别核心
