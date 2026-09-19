---
method_id: orderdep-failure-read-shadowing-module-global-before-polluter-hunt-180ebcaf9fce
name: orderdep-failure-read-shadowing-module-global-before-polluter-hunt
description: 当测试单文件通过、全量套件按序失败，且断言显示 per-test 的 env/monkeypatch 配置未生效（如结果集合为空）时，真正的未知量是'哪个模块级可变状态在运行中被绑定并遮蔽了测试隔离'。应先读被测模块的配置/路径解析函数，找到可被 configure() 类调用钉死、从而永久遮蔽 env 覆盖的全局；再 grep 调用方闭环机制；用 autouse fixture 逐例重置修复。在付出昂贵全量重跑之前，先用'污染源文件在前+受害文件在后'的最小顺序复现验证。避免先宽枚举嫌疑测试或多轮全量重跑做二分。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:735:6017fcb5667c371bd266
evidence_refs: learning:learn:68467ef137e6
created_at: 2026-09-18T01:09:37.491657+00:00
updated_at: 2026-09-18T01:09:37.491657+00:00
---
## Trigger
同一测试单文件运行通过，但在全量套件中失败；失败断言显示依赖 monkeypatch/环境变量的配置未被读取（空集合、落错路径、开关未生效等顺序敏感症状）

## Discriminator
断言输出当时已同时给出两条事实：(a) 该用例此前单文件跑是绿的；(b) 全量序下 monkeypatch 的 env 未被读取（如 rows==[]）。二者并存即指向'存在遮蔽 per-test 隔离的模块级可变状态'——此时被测模块内部的 _resolved_path/configure 类解析函数是最窄下一跳，应先于在 tests/ 里枚举污染源

## Short path
- 对比单文件与全量结果，锁定仅在全量序中失败的用例，从断言差异提取'哪个 per-test 配置未生效'这一未知量
- 读被测模块的 env→路径/开关解析函数，找会在运行中被绑定的模块级全局或缓存（如 _LEDGER_PATH 被 configure() 钉死后遮蔽 env override）
- grep 该绑定的调用方（factory/config 构建路径），确认全量序中更早的测试会触发绑定，机制闭环；可顺手用 git show 对父提交归因以排除合并引入
- 修复：在受影响测试模块加 autouse fixture 逐例把全局重置为 None，注释写明根因（谁绑定、遮蔽了什么）
- 先跑最小顺序复现（任一会触发绑定的测试文件在前 + 受害测试文件在后）确认转绿，再付全量套件重跑成本
- 全量失败数回落到已在远端/父提交复现的预存基线即停，勿继续追预存红

## Stop conditions
- 最小顺序复现（污染源在前、受害文件在后）通过，且全量套件失败清单仅剩先前已在基线归因的预存项
- 发现失败并非顺序依赖（单文件同样失败）→ 退出本方法，转常规回归归因/bisect

## Verification
- 顺序复现转绿：污染源文件先跑、受害文件后跑，全绿
- 全量套件失败数与已知预存基线一致，无新增失败
- fixture 注释包含根因链：哪个调用绑定全局、遮蔽了哪个 env 覆盖

## Counterexamples
- 单文件运行也失败：是真实回归而非顺序依赖，应 bisect 代码变更而不是找共享状态
- 失败由并行执行、超时或资源耗尽引起：顺序复现无法复现，本方法不适用
- 模块全局是生产必需的持久单例（生命周期即语义）：盲目逐例重置会掩盖真实缺陷，应改为测试显式 configure/teardown
- 污染源是 os.environ 直接泄漏而模块并无缓存全局：重置模块全局无效，需要 autouse 的环境隔离
