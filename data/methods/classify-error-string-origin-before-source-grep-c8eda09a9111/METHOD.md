---
method_id: classify-error-string-origin-before-source-grep-c8eda09a9111
name: classify-error-string-origin-before-source-grep
description: 在代码库中为一条报错/拦截行为定位源码时，先判定报错文本的产出者：若逐字匹配标准库/框架异常消息（如 Python shlex 的 No closing quotation），该字面量不会存在于业务仓库，grep 无命中 ≠ 逻辑在仓库外。应改搜机制关键词（模块/函数名、import 行、调用点）与自定义错误码（snake_case raise 值）的 raise 站点。本集曾据两次字面量 miss 误判『分类器是 Host 侧黑盒』，后经搜 shlex 关键词发现就在本仓 review_host_admission.py，提案病根与修复设计随之改写。
aliases: 报错原文 grep 不到, 错误信息在仓库搜不到是不是外部代码, 标准库异常文本定位源码, No closing quotation 搜不到, 搜机制关键词不搜报错文案
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:636:bc160c69eb6f3552445a
evidence_refs: learning:learn:0684a2e896fa
created_at: 2026-10-29T01:09:32.169993+08:00
updated_at: 2026-10-29T01:09:32.169993+08:00
---
## Trigger
需要为一条已观察到的报错/拦截现象定位源码位置（写修复提案、根因分析、异常处理审计），正准备或已对报错原文发起仓库内容搜索；经验卡/日志/上游文档已给出报错文本与部分机制线索。

## Discriminator
报错文本的来源分类，且在搜索前即可完成：(a) 逐字匹配目标语言标准库/框架异常消息（英文散文式、可在 stdlib 文档查到，如 shlex ValueError 'No closing quotation'）⇒ 库消息，必不在业务仓库；(b) snake_case 带业务语义的错误码 ⇒ 仓库自定义字面量，应当可搜到 raise 站点。经验卡 body 若已写明机制（『shlex 解析失败』），该分类在动手搜索前就是已知事实，不需要事后倒推。

## Short path
- 对报错文本做一次来源分类：能否在标准库/框架异常消息中逐字找到？能 ⇒ 库消息；若为 snake_case 业务码 ⇒ 自定义字面量
- 库消息：跳过原文搜索，改搜机制关键词（如 import shlex / shlex.split 调用点）与包裹它的 except 捕获站，确认是否存在降级路径
- 自定义错误码：搜其 raise 站点，钉住所在文件与行号
- 两者均无命中且当前树无该机制调用点时，才允许『逻辑在外部（宿主/服务端）』结论，转行为探针取证而非继续换措辞 grep
- 定位后读取该段源码验证：无捕获的解析路径确实能产生该错误文本，外层错误码 raise 站点与现象闭环，停止

## Stop conditions
- 病根钉到具体文件+行号，读取回执与报错现象形成完整因果解释
- 机制关键词与自定义错误码均无命中且本仓库无调用点 ⇒ 外部结论成立，停止仓库内搜索转外部取证
- 用户所需事实（源码位置/异常处理现状）已被读取回执权威验证

## Verification
- 读取的源码段能复现错误文本的产生路径（如 list(lexer) 无 except 直接抛 ValueError）
- 自定义错误码的 raise 站点被内容搜索实际命中，与库消息的 no-match 形成对照，证明分类正确
- 最终结论不再依赖『黑盒/外部』假设，或该假设有 双关键词无命中+无调用点 的正面证据

## Counterexamples
- 报错文本本身就是仓库自定义字面量（如 raise ValueError('review_artifact_exceeds_cap')）⇒ 直接搜原文即命中，来源分类应压缩为一次心算，不值得单列步骤
- 报错来自外部服务/平台（HTTP 403、CI 平台文案）⇒ 搜原文和机制关键词都无意义，应查外部文档或发探针铸权威回执
- 机制关键词在仓库多处命中（多个文件都 import shlex）⇒ 关键词命中只是起点，须再按自定义错误码/调用链细分到唯一站点，不能停在第一处命中
