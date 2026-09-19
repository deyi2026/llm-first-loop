---
method_id: pin-producer-contract-before-consumer-87fba2dc0ae8
name: pin-producer-contract-before-consumer
description: 新写调用方模块前先固化被调用方真实契约（入口签名+封闭结果词表），并用符号解析（import/grep）而非语法解析验证新文件，避免在想象契约上堆叠代码后返工。
status: candidate
source_model: glm/glm-5.3
teacher_refs: method:method-self-distill-root-cause,method:method-self-distill-repo-api,method:method-self-distill-ab
source_episode_refs: session:2274a444-654d-46a3-a72b-2d83058b2289
created_at: 2026-09-09T18:50:37.755626+00:00
updated_at: 2026-09-09T18:50:37.755626+00:00
---
trigger:
- 即将一次性写出较长的 caller 模块，其核心路径调用另一既有模块的入口函数并按其返回值分支
- 新文件计划只用 ast.parse/语法检查验证
discriminator:
- 被调用方的现有入口在先前读取中已出现（旧 import 行与已读源码只见过旧入口），而 caller 引用的函数名、kwargs、返回 reason 字面量在任何工具结果中都从未出现过——契约尚是想象的，此事实在下笔前即可观察
short_path:
- 先固化契约：完整读到真实签名，或先在 producer 侧写出新入口并定义封闭的 reason 常量集合
- 再写 caller，分支逻辑只引用已存在的签名与常量
- 新文件用 import（符号解析）验证；编辑既有代码前先 read 精确原文再构造 old_string
- 小文件（如 <500 行）预计整体都要用时一次读完，避免多段重叠窗口与重复读
stop_conditions:
- caller 引用的每个符号都能在当前树 grep 到定义，import 新模块成功
- 分支所用字面量与 producer 定义一致
verification:
- python -c "import 新模块" 可立即暴露 ImportError（语法通过≠契约成立）
- 对 caller 中每个被分支的字符串常量 grep 其 producer 定义处
anti_patterns:
- 先写大 caller，再逐段读 callee 试图事后长出入口；状态映射硬编码尚不存在的返回字面量
- 用记忆里的代码拼 old_string（编辑失败信息已提示须先读精确文本）
counterexamples:
- 全新子系统、callee 尚不存在且无既有代码需互操作，caller 即设计规格，可 top-down 先写
- 有 mypy/Protocol 或立即跟进的运行测试在环时，书写顺序不敏感
programizable:
- 新建 .py 后自动跑 import 检查；提取 from-import 的名称并 grep 目标文件 def；检测同文件重叠读区间
model_owned:
- 判断缺口应补在 producer 还是改 caller；判断已读签名是否足以冻结契约
why_shorter: 把“让既有模块事后迁就想象 API”换成一跳可验证的契约固化，避免在未落地契约上继续堆码与返工。
