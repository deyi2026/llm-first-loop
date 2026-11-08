---
method_id: monitor-alarm-decompose-reader-writer-divergence-and-identity-capability-ee1e6cea672e
name: monitor-alarm-decompose-reader-writer-divergence-and-identity-capability
description: 状态面板/监控对已独立确认存活健康的服务进程报否定谓词（『无 startup manifest』『head 不匹配』）时，不当作进程故障、也不直接进入换形态/重启等修复实验：先把谓词分解为三个机械锚点——①监控读取的确切目录，②活进程实际写入的目录（不同服务可能挂不同 data_dir 根），③该部署形态能否自报比较所需的身份字段。目录分歧用最小对齐修复（软链/统一 data_dir）；形态结构性产不出身份（如 wheel venv 无 git → head 恒 unknown）则宣判『任何重启不可达』，把换形态（含 env/venv 锚点预检）或改 desired 列为决策项，而非用切换实验试错付出停机代价。
aliases: 面板说没有manifest但服务在跑, 报警找不到文件其实写在别的目录, 面板读的目录和服务写的目录不是同一个, 服务面板黄牌身份对不上怎么判, 非git安装的服务自报版本unknown
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7007267a-8cde-4b7c-bcc4-b677b3653671:126:535ce76dc263a2c3e6ae
evidence_refs: learning:learn:6fc73cb6a7bd
created_at: 2026-11-07T06:37:03.833533+08:00
updated_at: 2026-11-07T06:37:03.833533+08:00
---
## Trigger
面板/监控对某服务报『缺失 artifact（无 manifest）』或『身份不匹配（head mismatch）』，而该服务进程已被独立证据确认存活且健康（ps 存活、真实健康端点 ok）；用户要求读代码核报警条件而非猜测

## Discriminator
判定代码里报警的读取路径（如 store.runtime_dir/文件名模式）与生产者的写入语义（每服务写自己 data_dir/runtime）是否同一目录；结合 ps 看到各服务从不同根运行（wheel venv vs 仓库 venv），即可在动手前判出『缺失=目录分歧』；再读 manifest 写入方的身份计算逻辑（git_head 取自模块 git checkout 可用性），判出门槛是否形态性不可满足——这些都是报警实验前已可见的事实

## Short path
- 1. 独立确认进程事实：ps 三 pid 存活 + /health ok → 报警不是进程问题
- 2. grep 报警 reason 字符串定位判定代码，读出谓词成立条件与读取路径（绿 = manifest 在读取目录 ∧ pid 活 ∧ live.git_head==desired）；md5 比对运行侧文件确认所读即真实逻辑
- 3. 对『缺失』类报警：从每个活进程的运行根（argv/venv/配置）推导其写入目录，并排 ls 监控读取目录与各进程写入目录 → 直接证实/证伪『目录分歧』，找到实际存在的 manifest（head=真实谱系）
- 4. 对『身份不匹配』类报警：读 manifest 写入方如何计算身份字段 → 若该形态结构性产不出（git_available=false），判定任何重启/同形态重启不可达，不进入切换实验
- 5. 分歧→最小对齐修复（软链到读取目录）并回读面板确认谓词如实变化；形态不可满足→输出三条收敛路线（接受现状/重锚 desired/构建带身份的 release）交用户拍板

## Stop conditions
- 每个报警 reason 都映射到机械成因（目录分歧/形态无身份可自报/确实未部署）并有目录列表或代码行佐证
- 对齐修复后面板谓词如实变化（missing→真实身份显示），且全程未发生无预检的服务切换或停机

## Verification
- 并排 ls 读取目录与写入目录，读生产者实际写的 manifest 内容（pid/git_head）与面板显示逐字段对齐
- 本地所读判定代码与运行侧文件做 md5 比对，排除『读的不是真实逻辑』
- 『结构性不可满足』断言必须落在身份计算代码（git 可用性来源）上，不得凭『是 wheel』猜测

## Counterexamples
- 监控与生产者单根同目录设计：『缺失』就是没写，应查写入方/启动流程，目录分歧假设不适用
- 进程确实已死或漂移：报警是存活事实，先修进程再谈其余
- 身份字段构建期嵌入（wheel 自带版本串可自报）→ 重启可满足门槛，不可宣判不可达
- 面板只是轮询缓存延迟（15s 刷新窗口内）：先重取状态再诊断
