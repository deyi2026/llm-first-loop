---
method_id: resolve-missing-path-by-unique-token-not-tree-enumeration-418d71a1ca97
name: resolve-missing-path-by-unique-token-not-tree-enumeration
description: 当路径探测返回明确的『不存在且此前已登记不存在』回执时，把它当作定位问题而非内容问题：不要用全仓库 ls/find 枚举来补偿，不要用泛化文件名搜索（会得到多条歧义命中），也不要重试同一相对路径。先 pwd 确认 cwd，再用手头最具选择性的唯一 token（带时间戳的 run-id 或精确文件名）做一次窄域 search/find，直接得到唯一权威绝对路径，然后在该路径验证 artifact 内容与新鲜度，并在该工作区内执行后续动作。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:638:8e282acd3807a72083ce
evidence_refs: learning:learn:f475c2c6d8f6
created_at: 2026-09-21T02:52:06.711599+00:00
updated_at: 2026-09-21T02:52:06.711599+00:00
---
## Trigger
路径/文件探测返回『not found（且已登记不存在，建议 search 定位或求证）』类回执；任务上下文中已存在指向该 artifact 的全局唯一 token（如带时间戳的 run-id、精确文件名）；cwd/工作区根未验证。

## Discriminator
失败回执本身已明确建议定向 search 而非重试，且失败路径中已嵌入高选择性唯一 token（时间戳型 run-id）：这两条当时已知事实可把『仓库根下任意 eval 目录』缩为『一次窄域搜索应得唯一权威路径』，因此全仓库枚举与泛化名搜索（如 run_ab.py 得 7 条歧义命中）均无必要。

## Short path
- 收到『不存在且已登记不存在』回执后，先 pwd 确认 cwd，判定这是相对路径/工作区不匹配而非文件未创建
- 用最具选择性的已知 token（唯一 run-id 或精确文件名）做一次窄域 search_files / find -name，预期得到唯一绝对路径
- 在解析出的绝对路径上重探目标 artifact 并验证内容与新鲜度（如 gates G1-G4 all_ok=true、ts 为最新）
- 路径确认后才读入口/manifest 核对动作参数（如 Stage-A 行集恰好为预期集合），再在已解析工作区内启动执行
- 若唯一 token 搜索 0 命中，转向核实 artifact 是否刚被创建或从未创建（创建日志/向用户求证），而非扩大枚举

## Stop conditions
- 目标 artifact 的绝对路径已验证存在，且内容/绿灯状态/时间戳满足本次动作的前置条件
- 或已有证据表明 artifact 从未创建（唯一 token 0 命中且无创建记录），此时停止搜索并向用户报告/求证

## Verification
- 在解析出的绝对路径上重读 artifact，回执为 success 且内容符合预期 schema（如 gates all_ok=true）
- 后续命令均显式 cd 到已解析工作区，不再发起 cwd 未知的相对路径探测
- 复盘搜索命中数：唯一 token 应为 1 命中，若出现多命中说明 token 选择性不足，需追加判别信息而非逐个尝试

## Counterexamples
- artifact 确实从未被创建（唯一 token 0 命中且无创建日志）：此时应求证用户或检查生成流程，『唯一命中』预期不成立，不应套用本方法继续定向搜索
- 环境中无索引式搜索工具：应改用按唯一 token 限定的 find -name；反模式只是无界全树枚举，而非 find 工具本身
- 回执是瞬态超时/权限错误而非『已登记不存在』，或路径本身是绝对路径：重试原路径可能是正确动作，无需做定位再解析
