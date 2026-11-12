# LFL GitHub CI 反复失败：根因与最小修复方案

日期：2026-11-10（北京时间）

本轮结论：本次 8 条失败可归为 5 类有明确修复路径的问题；近 4 次 push 中，7 条相同失败持续存在，最新两次另有同一条时序测试失败。主要问题是测试环境、fixture 与执行入口不一致。不能据此保证未来 CI 永不失败，也不能将当前红灯直接忽略。

本轮完成日志审查、精确提交源码核对和浏览器时钟复现；未修改项目源码、规则或 CI，未执行完整 R9、push、合并、服务重启或生产部署。

## 1. 本次失败的事实

- 工作流：[CI #224 / run 42829592885](https://github.com/deyi2026/llm-first-loop/actions/runs/42829592885)
- 精确提交：`e64d67b9237c4a3f76695c4d3c6f2db1942a5650`
- [失败 job 129875854772](https://github.com/deyi2026/llm-first-loop/actions/runs/42829592885/job/129875854772)
- 环境：Ubuntu 26.04（`ubuntu-latest`）、Python 3.13.18，`uv sync --frozen --extra dev`。
- Ruff、Pyright 步骤均完成且未检出新增诊断；失败发生在 pytest，退出码 1。
- pytest：**8 failed / 14,438 passed / 170 skipped / 23 deselected / 3 xfailed**；耗时 17 分 49 秒。
- x86_64、aarch64 Linux 真实成品安装验收均通过；安全扫描与部署环境泄漏检查通过。
- 两项 nightly 检查在 push 事件下按条件跳过，属于预期行为。

“1 failing check”指一个聚合 job 失败，内部实际包含 8 条失败。已通过的安装验收只证明它实际执行的路径，不等于三服务 systemd 受管生产验收通过。

## 2. 反复出现的证据

独立读取以下四个 push 的门禁日志，而非仅根据工作流红色状态推断：

| push 时间（北京时间） | run | pytest 结果 | 失败变化 |
|---|---|---|---|
| 11-10 10:24 | [42742568256](https://github.com/deyi2026/llm-first-loop/actions/runs/42742568256) | 7 failed / 14,409 passed | 共同的 7 条 |
| 11-10 12:27 | [42755939586](https://github.com/deyi2026/llm-first-loop/actions/runs/42755939586) | 7 failed / 14,416 passed | 相同 7 条 |
| 11-10 20:42 | [42818054951](https://github.com/deyi2026/llm-first-loop/actions/runs/42818054951) | 8 failed / 14,438 passed | 共同 7 条 + 浏览器等待 |
| 11-10 21:59 | [42829592885](https://github.com/deyi2026/llm-first-loop/actions/runs/42829592885) | 8 failed / 14,438 passed | 同上 |

本轮抽样最近 15 个仓库运行记录，其中 7 个 push CI 均为 failure；只对上表 4 个读取完整门禁日志，因此不把其他运行也归为同一根因。

## 3. 五类根因与修法

### 3.1 未声明的测试依赖：1 条

节点：
`tests/peer/test_peer_contract.py::test_wayland_manifest_example_is_schema_valid`

该测试直接导入 `jsonschema.validators`，但该提交的 `pyproject.toml / dev` 未声明 jsonschema，`uv.lock` 也没有它。干净 runner 按冻结锁安装后必然缺失。

修法：将 jsonschema 加入 dev 依赖并更新锁文件。测试必需依赖缺失应提前报错，不用 importorskip 消除必要覆盖。无需因此把它加成产品运行依赖。

证据：[测试](https://github.com/deyi2026/llm-first-loop/blob/e64d67b9237c4a3f76695c4d3c6f2db1942a5650/tests/peer/test_peer_contract.py#L72)、[依赖声明](https://github.com/deyi2026/llm-first-loop/blob/e64d67b9237c4a3f76695c4d3c6f2db1942a5650/pyproject.toml#L30)。

### 3.2 沙盒 argv 单测没有隔离新增实跑探测：2 条

节点：
- `tests/test_sandbox_scope_roots.py::test_sandbox_argv_default_roots_identical_to_legacy`
- `tests/test_sandbox_scope_roots.py::test_sandbox_argv_passthrough_writable_roots`

fixture 仅伪装 darwin、二进制存在和可执行。产品实现已改为实跑探测 sandbox-exec 能否套用 profile，因此单测仍会在 Linux 上真正调用 `/usr/bin/sandbox-exec`，报 FileNotFoundError。

这是 mock 边界落后于实现。修法：argv/profile 单测显式替换外部可用性探测，专注验证生成结果；真实沙盒探测的成功、缺失、套用被拒保留独立测试，macOS 原生能力在适用环境验收。不能通过生产改成 `EXEC_SANDBOX=none` 或削弱显式配置的 fail-closed 行为过门。

证据：[fixture](https://github.com/deyi2026/llm-first-loop/blob/e64d67b9237c4a3f76695c4d3c6f2db1942a5650/tests/test_sandbox_scope_roots.py#L202)、[实跑探测](https://github.com/deyi2026/llm-first-loop/blob/e64d67b9237c4a3f76695c4d3c6f2db1942a5650/src/llm_loop/tools/sandbox.py#L135)。

### 3.3 假安装 fixture 进入真实 systemd 分支：3 条

节点：
- `tests/unit/test_linux_installer_scripts.py::test_missing_uv_is_bootstrapped_from_official_release_with_verified_checksum`
- `tests/unit/test_linux_installer_scripts.py::test_install_upgrade_rollback_failed_upgrade_and_uninstall_preserve_user_data`
- `tests/unit/test_linux_installer_scripts.py::test_active_pointer_write_failure_restores_both_version_pointers`

fixture 的 wheel 只有 METADATA；fake uv 创建解释器链接和假 lfl 命令，没有真正安装 llm_loop。旧事务测试假设所有必要外部行为都已替换，但安装器新增了 systemd 探测及 Python install-units 调用，fixture 未同步隔离。

runner 存在可访问的 user manager 时进入真实路径：
- 两条失败为 `No module named llm_loop`；
- bootstrap 测试使用另一解释器环境走得更远，实际调用 systemctl enable，报单元不存在。

因此测试结果会受解释器、PATH、环境变量和用户级 systemd 可用性影响。更换 HOME 并不能保证 user manager 与临时 HOME 属于同一套环境。

修法：事务单测完整替换 systemctl，默认明确模拟 user manager 不可用；需要验证 managed 分支时，使用真正包内容或符合调用契约的测试替身，并对 unit 生成、失败、启动/禁启动行为独立验收。绝不能让 fake wheel 的单测操作宿主服务。

真实成品验收使用真实 wheel，环境也更干净，故可以通过。这两种测试覆盖和输入不同，结果不矛盾。其通过仍不能代替真实用户会话下三服务受管验收。

证据：[fake uv / fixture](https://github.com/deyi2026/llm-first-loop/blob/e64d67b9237c4a3f76695c4d3c6f2db1942a5650/tests/unit/test_linux_installer_scripts.py#L112)、[安装器 systemd 分支](https://github.com/deyi2026/llm-first-loop/blob/e64d67b9237c4a3f76695c4d3c6f2db1942a5650/scripts/install_linux.sh#L482)、[真实成品验收环境](https://github.com/deyi2026/llm-first-loop/blob/e64d67b9237c4a3f76695c4d3c6f2db1942a5650/scripts/verify_linux_installer.py#L146)。

### 3.4 构建测试需要 WebUI，所在 job 没准备：1 条

节点：
`tests/unit/test_linux_installer_scripts.py::test_built_wheel_metadata_requires_socks_extra`

测试在 pytest 中执行真实 uv build。setup.py 要求 `webui/dist/index.html` 已存在；test job 没构建 WebUI，必然报 `Missing Web UI`。

另一个 linux-installer job 虽然构建了 WebUI，但 job 各自有独立工作目录，不会自动共享文件。本地 ci_gate 已有 WebUI 准备，进一步造成“本地可过、GitHub 不过”的错觉。

修法优先选择一个最小方案：
1. 在保留该测试的 job 内安装冻结的 Node 依赖、构建候选 WebUI，再跑 pytest；或
2. 把对真实 wheel METADATA 的断言放到现有真实成品构建 job，使用它已生成的同一个 wheel，并明确留下该断言的覆盖记录。

不为这条测试删除 setup.py 的成品完整性要求，也不跨 job 假定产物存在。

证据：[构建测试](https://github.com/deyi2026/llm-first-loop/blob/e64d67b9237c4a3f76695c4d3c6f2db1942a5650/tests/unit/test_linux_installer_scripts.py#L597)、[打包前置](https://github.com/deyi2026/llm-first-loop/blob/e64d67b9237c4a3f76695c4d3c6f2db1942a5650/setup.py#L34)、[CI](https://github.com/deyi2026/llm-first-loop/blob/e64d67b9237c4a3f76695c4d3c6f2db1942a5650/.github/workflows/ci.yml)。

### 3.5 语义测试绑定真实 1 毫秒截止时间：1 条

节点：
`tests/unit/test_smc_browser_typed_wait_v06.py::test_typed_object_wait_preserves_complete_absence_vs_partial_indeterminate`

测试期望完整覆盖下的对象缺失为 satisfied，却只给快照采集、落盘和判定总共 1ms。实现会在样本完成后检查截止时间，晚到的成功降级为 indeterminate。runner 稍慢时，当前断言就会失败。

本轮在临时目录中，直接调用相同测试 fixture 和生产实现，并只控制时间边界，得到：

| 场景 | 结果 | reason |
|---|---|---|
| 完整覆盖、截止前完成 | satisfied | 无 |
| 部分覆盖、截止前完成 | indeterminate | coverage_incomplete_for_absence |
| 完整覆盖、模拟耗时 2ms、预算 1ms | indeterminate | deadline_exceeded |

复现退出码 0。所用浏览器实现及测试文件与失败提交无差异。它证明当前断言受时间条件影响；未模拟完整 GitHub 硬件环境，不以本机耗时估算 runner 性能。

修法：这条覆盖语义测试采用可控时钟，使“完整/部分覆盖”的判断与 CPU/磁盘速度脱钩；截止时间和晚到样本另用现有时钟控制模式验证，保持超时保护与原断言含义。单纯增大 sleep 或无限重试不是根治。

证据：[1ms 测试](https://github.com/deyi2026/llm-first-loop/blob/e64d67b9237c4a3f76695c4d3c6f2db1942a5650/tests/unit/test_smc_browser_typed_wait_v06.py#L480)、[截止检查](https://github.com/deyi2026/llm-first-loop/blob/e64d67b9237c4a3f76695c4d3c6f2db1942a5650/src/llm_loop/tools/builtin/browser_wait.py#L383)。

## 4. 为什么修本地门禁后 GitHub 还会红

已核对该失败提交：
- 本地 ci_gate 构建 WebUI、设置候选 PYTHONPATH、隔离 HOME，并将信号测试单独运行。
- GitHub test 仍单独写 uv sync、Ruff、Pyright、串行 pytest，未复用这些准备步骤。
- GitHub test 使用 ubuntu-latest，本次已是 26.04；安装验收固定 24.04。
- 本地残留依赖及 macOS 原生能力可以遮住干净 Linux 上的缺口。

本轮远端本地仓库观察到 main 为 `270581ea793f962e60e3796b272f2af2aedc1b8f`。相对失败 SHA，依赖声明、上述测试、CI 和本地 ci_gate 相关路径没有新差异；不能认为后续知识卡提交已修好这些问题。

11 月 9 日优化建议提过执行口径分裂。本轮日志使其中部分风险有了具体失败节点。也观察到本地 ci_gate 已有后续加固，不能把昨天报告的每项旧状态都当作当前事实。

## 5. 建议的最小实施顺序

1. 一次补齐五类问题：dev 依赖和锁；沙盒探测替身；systemd 隔离；wheel 测试前置或归位；浏览器可控时钟。
2. 在干净 Linux 环境先跑这 8 个失败节点及相关 fixture 测试，尽早验证根因；保持真实 Linux 双架构安装验收。
3. 让本地与 GitHub 共享准备步骤和测试集合定义，避免继续复制三套流程。保留现有 CI job 名，逐步复用已有实现，不另造门禁系统。
4. 把依赖与必需产物检查放在长耗时阶段前；保存 JUnit 和失败日志，直接显示失败节点，减少每次人工翻完整日志。
5. 对最终候选按现行适用审查与测试要求完成一次验收，再推送验证 GitHub。相同输入无变化不原样反复重跑。

Ubuntu 可固定为明确支持版本以减少镜像漂移，但它只提高可复现性，不能代替修复 mock 和依赖。未来平台支持升级时，显式更新并验收即可。

## 6. 完成标准

- 干净冻结依赖环境能导入必要测试依赖。
- argv/profile 单测不调用宿主 sandbox-exec；真实探测失败保护仍有效。
- 假安装事务测试不调用真实 user manager，不启停宿主服务。
- wheel METADATA 断言在具有真实构建前置的路径中执行。
- 覆盖语义测试不再依赖 1ms 真实耗时；截止前/后行为均可确定验证。
- 最终提交对应的 GitHub 门禁退出码 0，双架构成品验收保持通过，测试覆盖变化有明确记录。

这批问题可以通过具体工程修复消除。“根治”的目标是消除这些已知重复失败和形成它们的准备/隔离缺口；新产品缺陷仍应正常触发红灯。

