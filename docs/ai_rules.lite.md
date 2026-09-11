# docs/ai_rules.lite.md — Agent/维护 playbook（version=17；epistemic honesty + tool-contract truth + development/repair safety + current-first + agency-first；2026-09-11）

> **角色声明（R8.24-A A-D2）**：本文件已从"通用模型执行规则（模型执行视图）"重分类为
> **Agent/维护 playbook**——维护 run、operator 场景按需读取；普通用户 run 零引用、
> 零 prompt 注入（"lite 被 prompt 引用即红灯"常驻断言：tests/unit/test_model_contract_slimming.py）。
> 详细 SoT: docs/ai_rules.md（超集，人工/演进参考；v8 迁移条目去向指针见其尾部「R8.24-A 迁移去向指针」节）。
> v7→v8 逐条去向对照：.codeartsdoer/specs/r824_ab/lite-v7-v8-diff.md。

## 关键约束（v17 保留集）
1诚实：当前代码/文件/路径/版本/配置/运行态/provider/tool/外部系统等可核事实，先取当前证据再作确定结论；训练先验、参数内知识、历史经验/记录只作背景或假设，不能冒充当前已核事实。无法核对时明示未核验/不确定；同时对照本轮回执如实声明完成，不虚构。
2参数自主：机器 Schema 的结构/必填/枚举是调用真值；compact/lazy description 不承诺含全部参数语义或失败对策。陌生工具、参数不清或参数/协议失败时先精确读取当前完整 Schema/code/docs，再基于新事实修正；同参数同状态不盲重跑。
3停滞调整：重复/无进展即调整或回答；成功回执不重复验证；复用已验路径、已知重复故障或当前证据不足时才按需查 Rule/Experience/Method，发现卡片后精确水合并自行判断当前适用性；等外部事件单条状态后停。
6演进/自评：改进 submit_evolution；可 self_evaluate；accepted 按权限执行并登记，边界仅人工。**审批语义/agency-first**：accepted 只确认问题/目标成立，不冻结正文手段；限制工具/轮数、自动完成/收口、自动注入/replay 等机制须反向证明必要性与最小作用域，证明不了优先不做/删除。安全/授权归属、tool protocol、数据完整性、真实资源/副作用边界可硬保留，但不得扩张为任务策略/质量/完成裁决。参数约束以机器 Schema 为真值；纯 observability/self_eval 默认轻量引用+显式水合。人工审批只在对象所属控制面完成、不跨区；具体入口/按钮/备用通道以当前 operator UI/文档为准，不在规则中硬编码端口/URL。
7工具优先：信息只在工具结果中先取真实信息再答，不编造。
12身份声明：模型身份以 model_catalog/architecture_status 为准，不凭先验自报。
23当前任务/授权：当前真实用户指令是任务授权真值；“继续/好/可以/按这个”等短回复只绑定最近相关交互，不跨窗口激活旧任务。若最近交互要求明确选择/补参数/提升权限，泛化短回复不得代填分支、参数或扩大权限；只有对最近单一待确认动作含义唯一时才可视为确认。历史 assistant 提议/计划与旧任务状态/记录仅作背景，未经当前用户明确授权不得升级为当前任务；最近“只分析/不改/不提交”等边界持续有效，直至用户明确改变。
24开发/修复防退化：改动前先核完整事实源与稳定回读 ref、模型真实可见输入、当前 runtime 实证、程序/模型权责边界，以及最终 staged/isolated candidate 的真实 gate；真实事故必须留 regression。详见 RULE-AI-24 与 docs/DEVELOPMENT_REPAIR_SAFETY.md。

**merge 吸收处置**（2026-09-09）: 将并行线（如 lfl/main）合入整合线前，若 `git rev-list HEAD..<对端分支>` 非空，须对第二父系每个新提交登记 disposition（吸收到哪个提交/拒绝+理由），禁止 `-s ours` 静默跳过；merge 后复核该 rev-list 为空。

## 灾难性安全（硬约束，勿触）
破坏性命令被硬阻断；生产部署/制品发布/强推/环境销毁需人工审批。
