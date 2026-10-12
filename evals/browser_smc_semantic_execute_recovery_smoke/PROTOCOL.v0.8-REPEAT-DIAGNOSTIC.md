# FC1 repeat / diagnostic（预先冻结）

## 处理与基线

- 完整运行源码取 `2794b2cd` 的隔离 committed checkout，包含 `src/` 与 `methods/` 全量 SHA256；不混入后续 `3b84ab2d` 的 Session/continuity 更新。
- harness SHA 与 runtime SHA 分列。worker 启动核对真实 import 源根目录及解析后轮数；每行开始前核对 runtime 源哈希、harness Git 身份、模型进程和配置。
- 六行计划、顺序、fixture、prompt、FC1、A/C/E、模型权重与服务参数沿用 v0.8。每行 fresh session / DATA_DIR / Chrome profile，串行且只用同一个 Ornith。
- 本轮新增的是 harness 观测：启动 surface 独立原子落盘、父进程终态落盘、原始事件日志离线计数与 fixture oracle 对应轮次。无模型可见 prompt/schema 改动，无自动重放、watchdog、FC2 或 A3 处理。

## 预先定义的两个 profile

| profile | 上限 | wall timeout | 资格用途 |
|---|---:|---:|---|
| repeat12 | 12 rounds | 240 s | 沿用主 Gate |
| diagnostic16 | 16 rounds | 240 s | 仅诊断，不能宣称主 Gate 通过 |

先完整运行 repeat12 六行，再完整运行 diagnostic16 六行。不是对失败行选择性重跑，不用新结果替换旧结果。
任一 run 的源码、模型、surface 或配置身份不一致时保留证据并停止混合采信。

## 超时与计数

`worker-startup.json` 在 engine.run 前持久化；正常终态仍写 `worker-result.json`。
父进程在 worker 退出或超时后读取两者与已经落盘的 raw，独立写 `worker-observation.json`；不改原始结果。
TIMEOUT 始终保持 TIMEOUT，主 Gate 始终因此失败；surface 缺失记 unknown，不填 false 或推定 exact。
未观察到的指标记 null；已读取的完整日志前缀可计数，但 `run_end_observed=false` 表明生成被截断。
partial-only 沿用既有 scorer 的 >=10 partial / 同轮无draft与dispatch定义，仅作离线观测，不干预生成。

## Oracle 与诊断解释

fixture 本身字节不变；harness 在收到 fixture 事件时记录 oracle 与此前已落盘的 tool.execution.started round。
`oracle-observations.jsonl` 不进入模型上下文，包含全部观察，后续动作使 oracle 失效时仍以最终 oracle 判结果。
分别报告首次满足 oracle 的 <=12、13–16、未满足、轮次未知四类，TIMEOUT单列。
延长轮数后成功仅为该基线的预算敏感性证据；不等于能力上限，不替代12轮门槛。
跨处理成功集不相交不能估计随机方差；一次同处理repeat仅补稳定性证据，不作显著性结论。

## 后续裁决

基于两臂结果再给 FC2 constrained semantic grounding 实现裁决，A3 依赖在其后。
target_ref 裸 URL 的自动选页/补版本仍不准入。D 独立诊断，禁止自动重放。
