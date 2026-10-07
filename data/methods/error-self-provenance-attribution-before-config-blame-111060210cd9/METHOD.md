---
method_id: error-self-provenance-attribution-before-config-blame-111060210cd9
name: error-self-provenance-attribution-before-config-blame
description: 当用户把一次带归属信息的运行时失败归因于某个静态配置值（base_url、model、provider、endpoint）时，先读失败记录自身内嵌的归属字段与会话/run 级 latched 生效状态做排除，而不是读代码或做单变量实验：仅存在于被覆盖静态配置、且与异常归属字段不一致的配置值，不在失败路径上，可直接排除。对'能否自动重试'的第二问，再沿异常类名定位抛出点，区分两类错误：传输级中断已有有界重试；流正常结束但语义为空（零内容零工具调用）通常绕过重试，需走提案/人工审通道修复。比根因实验法省掉冻结 baseline 与单变量控制的成本。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8098b445-b87e-4252-a938-91924f37f4db:28:a2770bc985d47b3db186
evidence_refs: learning:learn:2cd45326f0c5
created_at: 2026-10-07T10:58:59.598769+08:00
updated_at: 2026-10-07T10:58:59.598769+08:00
---
## Trigger
用户对一次运行时失败提出配置归因假设（'是不是 X 配置/地址引起的'）或追问该失败能否自动重试，且异常文本/异常日志自身携带归属字段（provider=/model=/session_id），或存在会话级 latched 覆盖状态可查

## Discriminator
失败记录自身内嵌的归属字段 + 运行时 latched 生效状态这两条当时可见事实：本集中用户贴回的错误文本已标注 provider=glm、model=glm-5.3，生效模型目录显示会话覆盖后的实际链路，而被怀疑的地址仅出现在被覆盖的静态 base_url 配置字段中——两条事实在未读任何代码前就把候选链路缩到一条，直接排除静态配置假设

## Short path
- 从用户提供的错误文本中直接提取内嵌归属字段（provider/model/session_id），锁定失败所在链路
- 查会话/运行时 registry 的当前生效 model 与 base_url，区分'latched 生效值'与'被覆盖的静态配置值'
- 若归属字段与生效状态一致且均不经过被怀疑的配置值 → 直接排除该归因假设，无需读代码或做实验
- 对'能否自动重试'：沿异常类名定位定义与抛出点，再仅查抛出点所在调用链的既有 retry/退避逻辑，按错误类别（传输级中断可重试 vs 流正常结束但语义为空、绕过重试）得出结论
- 结论需要修复时走既有演进/提案通道，并论证重试的副作用安全性（零内容零工具调用 = 零已提交副作用，原样重发幂等）

## Stop conditions
- 异常自归属字段与 latched 生效状态两个独立来源一致指向同一链路 → 配置归因问题裁决完毕
- 已在代码中确认该异常类在或不在重试路径上（引用抛出点与重试分支触发条件）→ 重试能力问题裁决完毕，转入提案或如实上抛

## Verification
- 归因结论必须由两个独立证据源互证：失败记录内嵌归属字段 + 运行时生效状态；仅有静态配置不能定案
- 对被排除的配置值，说明其在证据中的真实角色（仅存在于被覆盖的静态配置字段），而非笼统否认
- 重试结论须能指出异常抛出位置与既有重试分支的触发条件，并区分可重试与不可重试的错误类别

## Counterexamples
- 异常记录不含任何归属字段（如裸 transport error 无 provider/model 标注）→ 无法用自归属排除，需按 root-cause 流程冻结 baseline 做单变量实验
- 被怀疑的配置值与 latched 生效状态一致（确实在失败路径上）→ 归因字段不能排除假设，必须进入代码/协议级核查
- 失败发生在配置加载/覆盖机制本身（override 未生效、registry 污染）→ '实际生效状态'本身是待验证对象，不能再充当 discriminator
- 流式产物非空但内容损坏或工具调用参数错误 → 存在部分输出/副作用，'零副作用可安全原样重试'的论证不成立
