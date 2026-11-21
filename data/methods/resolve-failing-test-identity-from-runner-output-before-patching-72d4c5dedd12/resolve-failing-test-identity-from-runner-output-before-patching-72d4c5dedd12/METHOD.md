---
method_id: resolve-failing-test-identity-from-runner-output-before-patching-72d4c5dedd12
name: resolve-failing-test-identity-from-runner-output-before-patching
description: 行为改动后测试门变红时，失败测试的精确身份通常已由 runner 输出机械给出：traceback 的 `_ test_name _` 头或 FAILED path::name 汇总行，加上失败体自身的可观察特征（失败处是否调用运行型入口如真实 episode 执行，还是只读冻结回执的 IO）。先用这两点把候选函数缩到唯一一个并读完整函数体，再裁决删除/改读冻结回执/修实现。凭断言 snippet 或 docstring 的语义相似度去猜另一个名字相近的测试并打补丁，会打出无效补丁，多花一轮 patch+全量重跑才能回到正轨。
aliases: 测试红了先搞清是哪个用例挂的, 报错张冠李戴白改一轮, 按失败用例名定位再动手, pytest 红灯别急着打补丁, 失败归因先看完整报错头
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:dc9cbbb4-590e-40e1-b360-158e5ef5619b:493:39cfe6348af31028b7b5
evidence_refs: learning:learn:97a89a0221d3
created_at: 2026-11-19T10:41:01.441962+08:00
updated_at: 2026-11-19T10:41:01.441962+08:00
---
## Trigger
对已改动的代码跑 pytest 等测试门出现 failed，且下一步动作是对某个测试打补丁/重写/删除之前；或失败回执只露出断言 snippet、尚未确认失败测试的精确 file::name 时。

## Discriminator
runner 失败段的机械标识（traceback 头 `_ test_name _`、`FAILED path::test_name` 行）与失败体可观察特征（如失败行上一行是 `run_calibrated_episode(7)` 这类运行真实 episode 的调用，而非读取冻结回执文件的断言），两者共同把候选函数从多个缩到 1 个。

## Short path
- 跑测试套件，保留完整失败段输出（含 traceback 头与失败体上下文行），不凭尾部 snippet 直接归因
- 从失败段头/FAILED 汇总行取出精确测试标识；若标识被截断不可见，先低成本重跑收集或加 -rf 拿到名字，而不是先打补丁
- 用该精确名定位函数并读完整函数体，核对其调用形态与失败 snippet 是否指向同一函数
- 按函数体证据三选一：旧预期的运行型测试且职责已被正测/冻结回执测试覆盖→删除；历史事实需保留→改读冻结回执断言；确为实现回归→修实现而非动测试
- 一次 patch 后重跑至 0 failed，并核对测试总数增减自洽与静态门仍绿

## Stop conditions
- 失败测试已按精确标识定位、处理完毕，重跑 failed=0 且 passed 总数与删除/改写数量自洽
- 发现失败体的可观察特征与拟修改的测试不一致（张冠李戴信号）时，立即停止当前补丁，回到取精确标识这一步重新定位

## Verification
- 重跑 pytest：failed=0，且测试总数变化与本次删除/改写的数量一致
- Ruff/Pyright 等其余静态门仍绿
- 被删测试的职责在别处有等价覆盖（正测、矩阵、冻结回执测试），删除理由可审计

## Counterexamples
- 失败是实现回归（改动破坏了本应继续成立的行为）时，精确标识只用于定位，不能据此删测试，必须修实现
- runner 输出被截断且失败段头不可见时，先重跑或加 -rf 获取精确名，仍不许凭 snippet 语义猜测目标函数
- 多个测试同时红且共享同一 fixture/conftest 根因时，逐个测试打补丁是反模式，应先归因到共享层
