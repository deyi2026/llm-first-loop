---
method_id: honor-prescriptive-rejection-before-retry-96c602058bfc
name: honor-prescriptive-rejection-before-retry
description: 当提交类调用被参数校验拒绝，且拒绝回执本身是处方式的——点名缺失元素（如『可执行的当前性验证动作』）、指定落点字段（solution/body）、并给出示例模板——该回执即本次提交的完整修复契约。正确动作是用本集具体事实实例化该元素写入指定字段，对每条点名要求逐条自检后仅重投一次；合规重投仍遭同一拒绝则停止重试，改核对真实 schema 或换用能承载该元素的替代通道（元素随迁，如验证行写入 save_experience）。禁止未吸收规格的裸重试，也禁止丢弃点名元素的裸换通道。本集两次相同拒绝（EVO-20260923-6fe23c9b）即『规格已给却未被吸收』的直接证据；后续 save_experience 成功恰因携带了该验证行。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:8bc1cbb3-5fe5-44cb-9818-3acb329d2acb:878:ff01ea38df135312a2a6
evidence_refs: learning:learn:e5d3997ff556
created_at: 2026-10-11T18:55:47.925778+08:00
updated_at: 2026-10-11T18:55:47.925778+08:00
---
## Trigger
准备重试一次被参数校验拒绝的提交，且首次拒绝回执点名了缺失元素、落点字段与示例格式（处方式拒绝）。

## Discriminator
拒绝文本中已存在完整可执行修复规格：缺什么（可执行的当前性验证动作）、写到哪（solution/body）、长什么样（示例模板）；该规格在第二次尝试之前即完整可见，第二次出现相同拒绝文本即证明其未被采用——knowledge-at-time 成立。

## Short path
- 解析首次拒绝回执：列出点名缺失元素、目标字段、示例格式
- 用本集具体内容实例化该元素（如『当前性验证：重跑 model_catalog，若模型已换则本结论作废』），写入指定字段
- 对回执中每条点名要求自检新 payload，全部满足后重投一次
- 若合规重投后同一拒绝再现：停止该通道重试，核对真实 schema 或换用可承载该元素的替代通道，元素随迁不丢弃
- 收到接受回执且落盘记录可见验证动作后停止

## Stop conditions
- 回执确认接受，且持久化记录中含实例化（非模板占位）的验证动作
- 一次合规重投后仍遭同一拒绝 → 转入 schema 核对或通道切换，禁止第三次同型重试

## Verification
- 新 payload 的指定字段可检索到与本集绑定的具体命令/判据，而非回执示例的占位写法
- 接受回执与落盘记录均可见验证行（对照本集：save_experience 返回 verification_state=verified 且标题/正文含当前性验证动作）

## Counterexamples
- 拒绝消息不含修复规格（仅『参数无效』、403、超时）→ 无契约可循，应查 schema/权限，不套用本方法
- 点名要求与证据冲突：内容不支持任何真实可执行的验证动作 → 不得编造验证行，应如实记 unverified 或换通道时标注来源
- 拒绝源于环境/权限而非 payload 内容 → 补写元素无效，先修环境因素
- 存在既定 schema 且与回执模板不一致时 → 以 schema 为准一次修正，不逐字套模板
