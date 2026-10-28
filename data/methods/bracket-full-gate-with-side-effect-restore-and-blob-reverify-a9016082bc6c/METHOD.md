---
method_id: bracket-full-gate-with-side-effect-restore-and-blob-reverify-a9016082bc6c
name: bracket-full-gate-with-side-effect-restore-and-blob-reverify
description: 指纹冻结的候选以未提交工作树差分存在（HEAD==基线）且独立审查已 PASS 时，在同一工作树跑原版全量门禁（全量 pytest/CI）会把 tracked 副产物（reports/ 时间戳、ID 类重写）混进候选集，污染"同一候选"的绑定。协议：跑前固定候选身份基线（变更清单+逐文件 blob 哈希 vs patch 后像），跑后立即 diff 变更集，只 checkout 还原非候选副产物，再复验候选 blob 逐一一致，才可声称"过审的就是过门禁的同一候选"。内容一致性用 blob 级比对，不靠 git apply 退出码（那只证明可应用性而非同一性）。
aliases: 全量测试把工作树跑脏了怎么还原, 审查过了再跑CI候选还作数吗, pytest重写reports要checkout回去, 门禁跑完确认补丁没被动过, 同一份代码既过审又过测怎么证明
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:1ee6738f-0a1e-46fa-9522-fd9f35a8933a:1:084679d870d164020667
evidence_refs: learning:learn:dd9daf7ce8de
created_at: 2026-10-27T16:34:25.839565+08:00
updated_at: 2026-10-27T16:34:25.839565+08:00
---
## Trigger
冻结审查绑定的是工作树差分（改动未提交、HEAD==基线），审查 PASS 后用户授权在同一工作树运行宽执行面的原版全量门禁（全量测试/CI 套件）

## Discriminator
冻结材料=工作树差分 + 门禁命令是宽执行面全量套件：任何 tracked 文件被测试运行重写都会直接进入被审候选集；跑后 changed 文件数大于候选文件数即是该污染的即时可观察信号

## Short path
- 跑门禁前固定身份基线：git status 变更清单 + 每个候选文件 blob 哈希与 patch 后像逐一比对（blob 级，非 git apply 退出码）
- 逐字运行被准入的门禁命令（不复用改写）
- 跑后立即 git status/diff：changed 集大于候选集时，识别非候选的 tracked 副产物重写（reports/ 等）
- 仅对副产物路径 git checkout -- 还原，绝不触碰候选文件
- 复验：changed 集==候选清单且每文件 blob==patch 后像，通过后才在回报中绑定"审查与门禁针对同一候选"

## Stop conditions
- 复验后 changed==候选清单且 blob 全一致：可声称绑定成立，停止并回报
- 任何候选文件 blob 不匹配：候选已漂移、原 PASS 绑定失效，报告并请求重新冻结，不自行修补
- 审查留有 findings 且用户未裁决：原样保留候选（任何修改都会变更指纹）

## Verification
- patch index 前像==HEAD blob、后像==worktree 各候选文件 blob（跑前、跑后各核对一次）
- 跑后 changed 文件数与清单与冻结时逐项一致
- 还原操作只影响 reports/ 类非候选路径（git status 确认 HEAD 未动）

## Counterexamples
- 门禁命令无 tracked 写入（静态检查/只读分析）：无需还原步骤，跑后单次身份核对即可
- 候选已提交为 commit、工作树干净：测试副产物是 untracked/dirty，用 stash 处理即可，工作树差分绑定逻辑不适用
- 被重写的 reports/ 类产物本身在审查范围内：还原反而篡改被审材料，应保留并把重写纳入冻结指纹
- 审查材料因单文件超限无法绑定准入：属冻结前置问题，与本跑后协议无关
