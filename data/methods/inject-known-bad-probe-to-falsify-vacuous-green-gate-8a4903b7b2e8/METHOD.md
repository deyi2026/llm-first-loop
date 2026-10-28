---
method_id: inject-known-bad-probe-to-falsify-vacuous-green-gate-8a4903b7b2e8
name: inject-known-bad-probe-to-falsify-vacuous-green-gate
description: 给项目新增或接线校验门（typecheck/lint/test script、CI 检查步骤、hook）后，在当前无已知失败的树上跑出 exit 0 只证明"没有失败可报"，不能证明门真的在检查——config 路径写错、include 为空、命令 typo 静默跳过时同样是绿。宣布完成前做双向验证：正向=干净树 exit 0；负向=注入一个最小已知坏样本，要求门非零退出且报错定位到探针；随后删除探针并用 git status 确认树无残留。本集以临时类型错误文件使 typecheck 与 typecheck:fast 双双 exit=2，即删即净。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:48:c529cd1f731b9aadc159
evidence_refs: learning:learn:48e35d8ac892
created_at: 2026-10-21T11:21:38.663437+08:00
updated_at: 2026-10-21T11:21:38.663437+08:00
---
## Trigger
新增或修改一个校验/质量门（package.json script、CI step、pre-commit hook 等），且已在当前代码树上跑出通过结果（exit 0），准备据此宣布"已生效/已完成"时。

## Discriminator
当前树不含任何已知失败样本——此事实使"绿"对"门有效"与"门空转"（错误 config 路径、空 include 集、插件未加载、命令被静默跳过）完全无区分度；退出码只有在存在已知坏样本时才携带信息。

## Short path
- 在当前树跑门，确立基线：干净树 exit 0（若基线就红，先修既有错误，另案处理）
- 识别负向未知量：绿是否有效？构造最小已知坏样本（如一个含类型错误的临时文件），确保落在门声明的检查范围内
- 重跑门，要求非零退出且报错定位到探针；若仍绿，即门空转的直接证据，先修门配置再回到基线步
- 删除探针，git status 确认工作树无验证残留，避免把测试脚手架混入交付
- 双向证据齐备后宣布完成，并同步声明边界（如 fast 门仅供本地、不接入构建链）

## Stop conditions
- 干净树 exit 0 且注入已知坏样本时门非零退出（或按门语义显式报错），且探针已删除、树状态干净
- 门已有独立失败语义证据（CI 历史红过、仓库现存失败样本、上游命令被广泛验证）时，引用该证据替代探针，直接停止

## Verification
- 负向探针触发的报错定位到注入的文件/行，而非其它巧合错误
- 探针删除后 git status 干净；正向重跑门回到 exit 0

## Counterexamples
- 门所包装命令的失败语义已被既有 CI 红历史或现存失败样本证明——直接引用即可，无需重造探针
- 注入坏样本代价高或有副作用（对外服务门、长迁移、有状态 hook）——改用 dry-run 或一次性 fixture 沙箱
- script 只是对已验证命令的纯别名转发，自身无配置面，绿即有效
- 门设计为 advisory（违例只输出告警不改退出码）——负向判据应改为"是否输出预期告警"而非退出码
