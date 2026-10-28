---
method_id: blind-judge-via-inlined-inputs-and-mechanical-zero-tool-verification-e604f428f826
name: blind-judge-via-inlined-inputs-and-mechanical-zero-tool-verification
description: 需要独立盲评 judge 且存在不可泄露的参考标签时，盲性要靠输入构造与可观察行为机械保证，而不是靠更强的隔离机制：材料全文内联、零上下文继承、禁用工具，事后以『工具调用数=0、输入与标签无交集』验证。隔离通道只是运输层：发起前先探测其前置（如模型 provider 配置），或直接选已知可用的零上下文子代理通道，避免把任务押在未验证的 runner 上。分歧按三态落盘，不追加非预注册判据重跑。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d1e343a5-0eb5-4b62-b607-a8cd333ed256:15:783c04d0604a790d6b71
evidence_refs: learning:learn:06ab74c620a7
created_at: 2026-10-15T09:50:09.131223+08:00
updated_at: 2026-10-15T09:50:09.131223+08:00
---
## Trigger
任务要求一个独立 judge 对案例做标注/评分，且存在绝不能进入 judge 输入的参考标签或作者先验（盲评集 labels、标准答案等）。

## Discriminator
judge 任务按设计不需要任何工具或文件访问（纯内联文本即可判断，任务书本身已写明禁止执行命令）→ 盲性三要素＝输入内联、零上下文继承、零工具调用，全部可机械验证；因此进程隔离不是必要条件，通道自身的前置条件（provider/runtime 配置可用）才是发起前唯一必须先验证的未知量。

## Short path
- 确认 judge 所需判断材料可全文内联且无需读文件/执行命令；若做不到，则隔离与白名单才是主手段，本方法不适用
- 构造 judge 任务：案例全文内联，参考标签路径及其内容绝不进入输入，任务书显式禁用工具
- 通道决策：优先已知可用的零上下文子代理通道；若坚持外部隔离 runner，先用最小探测确认 provider/runtime 前置可用，再投入完整材料
- judge 结束后机械验证盲性：工具调用数=0，且 judge 输入与标签内容做包含性检查无交集
- 与作者标签逐题比对，按 一致=verified / 分歧=disputed / 判据不足=unknown 落盘可复算结果，声明单 judge 单轮不构成校准资格后停止

## Stop conditions
- judge 输出覆盖全部题目且两项盲性机械验证（0 工具调用、输入无标签）均通过
- 三态比对结果与判据已落盘可复算；不再为个别分歧追加非预注册的判据或重跑

## Verification
- 检查 judge 执行记录（job/子代理回执）中工具调用计数为 0
- 对 judge 实际输入与参考标签目录做内容交集/包含检查，应为空
- 重跑逐题比对脚本，三态结果可复现

## Counterexamples
- judge 必须读取仓库文件或运行代码才能判断（材料无法内联）→ 进程/沙箱隔离与文件白名单成为主手段，内联+零工具法失效
- 独立性硬性要求特定外部模型家族或真实外部 API → 通道的模型身份是硬约束，不能为可用性随意换成同家族或同上下文通道
- 参考标签尚未冻结、judge 跑完后还会改标签 → 机械盲性验证失去意义，应先冻结标签再组织盲评
