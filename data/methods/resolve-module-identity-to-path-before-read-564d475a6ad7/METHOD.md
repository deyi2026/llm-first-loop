---
method_id: resolve-module-identity-to-path-before-read-564d475a6ad7
name: resolve-module-identity-to-path-before-read
description: 检索命中给出的是模块引用（import/from X import、python -m、裸符号名）而非文件路径时，先把它当'身份'而不是'路径'：用一次确定性定位（按文件名搜索）解析出真实文件路径再读。对猜测路径的'不存在'失败回执否证的是整个同根猜测族，禁止换兄弟路径再猜。本回合该方法可省去 2 次失败 read、避免路径登记（TTL 24h）污染，并抑制后续返回同批命中的重复宽搜索。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:e8e83cd1-6d33-4a6b-b29b-56131638f5d7:0:8702658129522efd604f
evidence_refs: learning:learn:f5e04b3dfa29
created_at: 2026-09-18T18:54:12.515241+00:00
updated_at: 2026-09-18T18:54:12.515241+00:00
---
## Trigger
需要读取某实现文件，而当前掌握的位置线索只以模块引用形式出现（如测试文件内的 from llm_loop.runtime.service_control import），且尚无任何回执确立该包根（llm_loop/）相对仓库根的真实位置。

## Discriminator
命中行明确位于 tests/unit/test_managed_service_control_p0a.py 内、是 import 语句（from llm_loop.runtime.service_control import / from llm_loop.tools.builtin.service_control import）——这只证明模块身份存在，不证明文件路径；当时无任何回执表明 llm_loop/ 在仓库根；且首次 read 失败回执已明确'路径不存在/该路径此前已登记不存在（TTL 24h）——改用 search_files 定位'。以上均为失败动作发生前已可见的事实。

## Short path
- 按引用类型归位：import/python -m/符号名 → 只提取模块身份（llm_loop.runtime.service_control 等），不当文件路径使用。
- 一次按文件名的定位（search_files 'service_control.py'）拿到真实路径回执：src/llm_loop/runtime/… 与 src/llm_loop/tools/builtin/…。
- 读定位回执给出的真实文件：先结构视图，再关键段（字段表/常量/写路径）。
- 沿新暴露的引用边定位下一未知量：grep runtime_manifest → runtime/manifest.py 与 web 路由引用，每次检索对应一个明确未知量。
- 实现所需的全部事实源（desired store / live manifest / action receipt）定位并经回执验证后，停止发现，进入实现。

## Stop conditions
- 任何'路径不存在/文件不存在'失败回执出现：立即改为定位工具；禁止在同一错误根假设下尝试兄弟路径变体（路径登记已按 TTL 记录）。
- 目标文件已由定位回执给出路径并完成关键内容读取：停止定位类动作。
- 宽搜索开始返回与此前相同的结果集（再次命中同批测试文件）：停止该搜索分支，改用定向 grep/read。

## Verification
- 所读路径必须来自定位工具回执而非猜测映射；打开文件后其 import 与原始命中给出的模块身份一致。
- 对同一未知量的 guess-read 失败数为 0（至多 1 次且之后不再猜测）；无同根兄弟路径重试。
- 一个模块身份只需一次定位动作即收敛到文件路径。

## Counterexamples
- 命中本身就是带行内容的文件路径（如 'src/llm_loop/runtime/service_control.py:11: from …'）：直接 read，再定位是浪费。
- 仓库扁平布局此前已被回执确立（llm_loop/ 在仓库根下被列出或读过）：按模块路径直读正确，无需 src/ 假设。
- 定位工具不可用或连续失败：允许一次基于布局约定（src-layout 优先）的猜测读取；但收到'不存在'回执后仍不得换兄弟变体再猜。
