---
method_id: audit-patch-seams-binding-sites-and-call-pattern-compatibility-5f2248c495bc
name: audit-patch-seams-binding-sites-and-call-pattern-compatibility
description: 审查『importlib 复用既有测试模块 + 属性替换换传输/依赖』的候选时，核心未知量不是通读复用文件或重跑绿色回执，而是替换缝隙：被替换符号在复用代码中的全部绑定点位（模块级 import 之外，函数内局部 re-import 会从原包命名空间重新解析、绕过模块属性替换），以及适配器生命周期语义（如每请求自关 server）与复用代码每个调用模式（每请求新实例 / with 复用 / 同实例多请求）是否兼容。本集据此确认双点位替换必要且正确、单实例调用模式与自关语义兼容，并核验原断言对象直调、synthetic 边界、哈希与独立复跑后给出 PASS。
aliases: monkeypatch 模块属性没生效 局部 import 绕过, 审查复用旧测试换传输是否真生效, importlib 加载测试模块 替换 TestClient 审查, 双点位替换必要性怎么核, 适配器每请求自关 与原调用模式兼容性, 函数内 re-import 没被 patch 到
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a2e0db62-09ba-4556-929d-a18d3ca30273:0:854466afef145b2f1f56
evidence_refs: learning:learn:2e4f3ab12438
created_at: 2026-11-14T11:22:34.815590+08:00
updated_at: 2026-11-14T11:22:34.815590+08:00
---
## Trigger
只读审查一个通过 importlib/spec 加载既有测试模块、并把其中某个类（如 HTTP 测试客户端/传输函数）替换为自定义适配器的候选测试；或更一般地，审计任何『通过改写模块属性替换依赖』的代码是否真正在所有使用点生效

## Discriminator
两条当时即可从已读文件取得的有限清单：(1) 被替换符号在复用代码中的全部绑定点位——模块级 from X import Y 之外是否还存在函数体内局部 import 同一符号（局部 import 重新解析包属性，模块级 patch 对其无效）；(2) 复用函数内该符号的全部调用模式是否与适配器生命周期语义一致（适配器每请求后自关 → 只允许每请求新实例用法，不允许 with 复用或同实例二次请求）

## Short path
- git log/diff --stat 核验候选 SHA/TREE/基线与变更范围（纯新增、零生产代码）
- 读适配器测试文件，从其 docstring 提取它声称的『唯一改变』：替换哪个符号、以何种方式
- 对被复用模块定向 grep 该符号的两类绑定点位（模块级 import + 函数内局部 import）；发现局部 import 则要求替换覆盖双点位（模块属性 + 包属性），否则判失效
- grep 复用函数内该符号的全部调用模式，逐一与适配器生命周期语义比对（每请求新实例 ↔ 每请求自关；上下文管理器/同实例复用即不兼容）
- 确认复用函数是原函数对象被直调（签名与 conftest fixture 定义匹配），断言未被改写或绕过
- 核 synthetic 边界（被替换的底层传输函数零网络零 DNS）、文档/回执措辞诚实性、artifact 哈希 vs 回执，最后独立复跑新测试与原版等价子集

## Stop conditions
- 替换点位全覆盖、所有调用模式与适配器语义兼容、断言为原对象、哈希一致且独立复跑通过 → 出终审结论
- 发现任一未被替换路径覆盖的绑定点位，或任一与适配器生命周期不兼容的调用模式 → 判 REVISE 并给出具体文件与行号证据

## Verification
- 在复用模块内 grep 被替换符号的所有 import 形态，确认每一处都被实际替换路径覆盖
- 列出复用函数内该符号的每次调用，标注实例化方式，与适配器关闭/清理语义逐条比对
- 独立复跑：新测试通过 + 原版函数在原传输下等价子集仍通过（同一断言集两种传输均绿）
- artifact 哈希与回执登记逐字节比对

## Counterexamples
- 复用代码经依赖注入接收传输（非属性 patch）时，绑定点位枚举不适用，直接审注入点即可
- 被替换符号在复用代码仅有一处模块级 import 且单一调用模式时，双点位与多模式核对退化为一次 grep，不必展开全清单
- 审查预算禁止运行测试时，独立复跑步骤省略，静态缝隙核对仍独立成立
