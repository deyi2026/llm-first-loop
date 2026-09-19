---
method_id: code-nav-reuse-confirmed-paths-1e7e58c0f083
name: code-nav-reuse-confirmed-paths
description: 在多前端/混合布局仓库中做跨层代码定位时，把历史成功 grep/read 的命中路径当作下一跳的 provenance edge：新查询必须复用已验证路径或在已确认目录内窄 grep，只有无任何已确认路径覆盖目标 artifact 时才做目录级/全仓发现，且同一函数不重复整段重读。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: session:4d6c551c-a50d-4ef1-90cf-b0af9f557745
created_at: 2026-09-09T17:37:14.526788+00:00
updated_at: 2026-09-09T17:37:14.526788+00:00
---
name: code-nav-reuse-confirmed-paths
status: candidate
trigger:
  - 多 surface 仓库（如 legacy 静态 JS 前端与新框架前端并存、扁平路由文件与包式模块并存）中定位功能挂点
  - 工具历史中已存在对目标文件的成功的 grep/read 命中
  - 准备发出路径来自'猜测的目录布局'而非历史输出
discriminator:
  - 历史成功输出中已出现确切命中路径：广告文案所在的 owning 前端文件、含目标函数的扁平后端路由文件
  - 反向信号：新命令引用了历史从未出现过的路径布局（把前端目录想象进 src 包、把单文件路由想象成子模块）
short_path:
  - 用任务线索字符串（宣称的 UI 文案/快捷键）做一次全仓 grep，锁定 owning surface 的确切文件
  - 一次性读取该文件中目标函数完整区间，记录签名与门控逻辑
  - 跨层时用 grep -rn 'class X|def y' 一次性定位类/函数所在文件，只读命中行区间
  - 每个新查询的路径参数必须能在历史成功输出中找到出处
  - 三类挂点（前端发送门控、后端 busy 拒绝点、run 终态回调）读到具体代码即停，进入实现
branch_on_evidence:
  - observation: 已确认路径覆盖所需 artifact
    next: 行区间窄读，不枚举兄弟目录或 legacy surface
  - observation: 已确认文件不含所需符号
    next: 在已确认目录内窄 grep 符号，而非全仓猜新布局
  - observation: 无任何已确认路径可用
    next: 才做 ls/find/grep -r 发现，且一次性完成并记录新确认路径
  - observation: 命中来自文档/注释/另一 worktree
    next: 判别命中文件性质后再决定是否沿走
stop_conditions:
  - 各层集成挂点均已读到具体代码且签名已记录
  - 同一函数不再被第二次整段重读
verification:
  - 每个新命令的路径 ⊆ 历史成功命中路径集合
  - 无重复 (file, 行区间) 读取；无对已锁定 surface 之外兄弟前端的回头枚举
anti_patterns:
  - 猜测目录布局（虚构子模块路径、虚构包内前端目录）导致 ls/grep 失败后再全仓再发现
  - 对同一文件同一函数反复 grep + 分段 sed
  - 已通过文案 grep 锁定目标前端后，仍枚举 legacy 静态前端目录与其测试 conftest
  - 依赖不一定存在的现代文件工具（fd/rg），未探测即调用
counterexamples:
  - 任务本身要求全量盘点（如找出所有残留旧文案引用）→ 宽 grep 本来就是正确首步，复用单一路径会漏
  - 历史命中在 docs/注释/生成文件中而非 owning code → 沿走会误导，需先判别
  - 历史路径来自另一 worktree 或前缀已变 → 复用前须校验存在性
programizable:
  - 路径出处校验：新命令路径参数 ∈ 历史成功输出路径集合，否则标记为'猜测布局'
  - 重复读取检测：同一 (file, range) 二次读取即告警
  - 文件工具能力探测：优先 POSIX find/grep（恒可用）
model_owned:
  - 判断命中文件是否为 owning code（vs 文档/测试/生成物）
  - 判断跨层挂点证据何时已足够、何时 edge 断裂需扩大发现
why_shorter: 用历史已验证的路径 provenance 把'猜布局→失败→全仓再发现→重复重读'压成'沿已确认路径逐层窄读'，消除死路径与重复定位。
