---
method_id: shrink-gate-consumer-input-via-coverage-anchoring-b8606bee832f
name: shrink-gate-consumer-input-via-coverage-anchoring
description: 当门控消费者（独立审查/准入 child、子代理）对大输入反复返回空响应，且其输入由不可改写的 Host 机制（如从冻结未提交 delta 自动构建提示词、无法附加文件）决定时：不要原样重试，也不直接照搬或拒绝用户的具体修法（如『做成文件让它读』）。先从失败回执提取可检验假设（输入过大），找到机制真实输入通道中唯一合法可控变量，把已有权威 PASS 回执覆盖的大头锚定（提交）掉，只留真正未审的小残留作为消费者输入——既检验假设又保持覆盖链完整。本集 75KB→2.3KB 后窄审一次 PASS，随后全量门 exit=0；属单例证据，与 provider 抖动窗口存在混杂。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f3bcb24f-1f02-4da7-aaad-75bb446ffa88:562:eec2165db3f0baa6384b
evidence_refs: learning:learn:c9e53ca13b97
created_at: 2026-10-16T00:13:19.452427+08:00
updated_at: 2026-10-16T00:13:19.452427+08:00
---
## Trigger
门控下游消费者（审查/准入子代理）连续多次空响应（回执显示长时间处理/大量思考后零输出），且其输入由无法附加文件或改写任务书的 Host 机制从仓库状态自动构建；或用户提出与该机制冲突的具体修复建议。

## Discriminator
失败回执呈现『大输入→长处理→零输出』签名（指向输入侧而非工具死亡）；同时能辨认消费者的真实输入通道（如冻结未提交 delta）及其合法体积杠杆，并且输入可按审查 provenance 分区——一部分已有权威 PASS 回执覆盖，另一部分是真正未审的小残留。

## Short path
- 首个空响应后即停止对同一大输入的重试，读回执确认『长处理后零输出』签名，建立输入体积假设
- 定位机制真实输入通道（冻结未提交 delta），确认唯一合法杠杆是 delta 体积而非给 child 附加文件
- 按审查 provenance 把 delta 分区：已有 PASS 回执覆盖的大头 vs 未审小残留（如登记 JSON）
- 提交（锚定）已覆盖大头，使消费者输入只剩残留，并把覆盖链（早期回执→PASS 回执→窄审）留痕备核
- 对残留重跑准入：得到实质裁决则继续流水线；仍空响应则体积假设被证伪，转 provider/抖动诊断分支
- 在回执/经验卡中记录混杂因素（单例、provider 抖动窗口），不做单例机制性归因

## Stop conditions
- 缩小输入后消费者给出实质裁决（PASS/FAIL），进入下一流水线阶段
- 不存在任何具权威 PASS 覆盖的分区：为缩体积而提交未审内容会绕过门禁目的，此时不得应用
- 空响应在小输入下复现，或回执显示 schema/鉴权/超时等明确错误——假设证伪，换诊断分支

## Verification
- 残留准入 PASS 的 candidate_sha256 与锚定提交后的树状态一致
- 下游全量门 exit=0，证明锚定提交未破坏质量链
- 覆盖链三段可追溯：前序回执→已覆盖部分 PASS 回执→窄审 PASS
- 经验/回执已标注单例证据与 provider 抖动混杂，未被当成已证机制

## Counterexamples
- 小输入下同样空响应（provider 侧抖动/限流）——缩体积无效，应退避重试或换 provider
- 机制本就支持给 child 附加文件或改写任务书——直接照用户原话执行，无需翻译等效动作
- 全部输入均未经审查、无任何权威覆盖——提交以缩输入等于绕过审查，禁止
- 回执已给出明确失败原因（工具 schema、鉴权错误、真超时）——修该错误，而非猜测输入体积
