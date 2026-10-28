---
method_id: rerun-unchanged-arm-as-test-retest-before-gate-acceptance-cd35e9de929a
name: rerun-unchanged-arm-as-test-retest-before-gate-acceptance
description: 预注册配对实验需重跑（如更换阴性对照臂）时，把未改动臂的同批重跑当作免费 test-retest 样本：跑前预注册它与冻结旧批的逐实例一致率阈值和逐 check 分解作为 FAIL 条件。字面门槛全过但一致率低于阈值（尤其集中于个别词面判据 check）时，说明 rep=1 逐实例判定被采样噪声支配，零容差门槛结果不可采信；修复指向判分单位（多次采样多数投票/结构判据/人工复核），而不是迭代处理变量（换卡、扩词表）。同一 check 在两种不同处理下都是失败位点时，缺陷在仪器不在处理。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:40fc9238-e2b7-4c72-a023-f7e53ee023da:675:5671f08bb94ae81e917c
evidence_refs: learning:learn:ce4563967c33
created_at: 2026-10-19T22:34:15.522140+08:00
updated_at: 2026-10-19T22:34:15.522140+08:00
---
## Trigger
预注册配对 A/B 实验因更换其中一臂（如重设计阴性对照）需要重跑；另一臂旧批逐实例结果已冻结、可离线重判；判分为单次采样（rep=1）的机械 check，且门槛含零容差或 check 级条件

## Discriminator
未改动臂新旧两批的逐实例一致率与逐 check 一致率——两批 calls 文件都已存在，离线重判即可算出，无需新模型调用；低于预注册阈值或集中于个别 check，即为采样噪声支配/词面代理的直接证据

## Short path
- 设计重跑时把未改动臂也纳入同批执行（不继承旧结果），免费获得 test-retest 样本
- 跑前预注册两类诊断及 FAIL 条件：最小注入探针（测词面代理）+ 未改动臂新旧一致率阈值与逐 check 分解（测采样稳定性）
- 跑后先算字面门槛再算诊断：字面 PASS + 任一诊断 FAIL → 结果不可采信，禁止放行下一阶段
- 定位低一致 check 并分类缺陷：注入一句话即可翻=词面代理；无扰动双向翻=采样不稳
- 修复只指向判分单位（rep≥3 多数投票、结构判据、人工双评）；同一 check 跨两种处理复发时停止迭代处理变量

## Stop conditions
- 未改动臂一致率 ≥ 预注册阈值且注入探针不翻动 → 字面门槛可采信，按门槛裁决并停止诊断
- 无冻结旧批可比 → 明确标注单次结果无信度证据，不作为零容差裁决依据

## Verification
- 一致率从两批冻结 calls 文件离线重算，不新增模型调用；两批输入与卡的 sha256 与冻结文件核对一致
- 逐 check 一致率表定位噪声来源；归为采样噪声时翻动应双向（仅旧批 True 与仅新批 True 均存在）

## Counterexamples
- 臂为确定性程序或稳定低温度输出，重跑一致率恒≈1，诊断无信息量，可跳过
- 门槛只裁决聚合通过率且样本量充足：噪声在聚合层平均掉，逐实例一致率非必要条件
- 未改动臂重跑成本远超预算且旧批本身已有 rep≥3 采样：可继承旧批信度，不必为 test-retest 重跑
