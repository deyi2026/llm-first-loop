# smx.py 安全审查 + 职责去重（裁决点1 blocking 条件）

- 对象: tools/smx/smx.py · 585 行 · sha256 243874cfc0b8feb55d1e556812c2caa9d6f63b936d35c0de2344c0e82c5ec534 · 权限 600
- 方法: 全文人工通读 + 危险面 grep 定位 + 动态 PoC（/tmp 隔离环境，现场已清理）+ 职责对照（execute_command/search_files/read_file/schedule）
- 日期: 2026-09-12 · 审查者: LFL（llm-first-loop）
- 结论: **as-is 不过**。S1 为 blocking（形态问题）；S2/S3 必修（小补丁）；S4 应修。修复后可按「感知层工具」形态并入。

## 发现

### S1｜blocking：自建执行通道，绕过 execute_command 硬安全边界
- L314-316 `subprocess.Popen(["bash","-c", build_wrapper(cmd,nonce)], ...)`：smx 直接执行任意命令，无灾难性命令硬阻断。
- docstring L17-19 宣称「实际命令经调用方 shell（execute_command 通道）执行，安全边界完全继承该通道，不提供任何越权能力」——**对代码不成立**。该宣称只在实验用法（模型经 execute_command 调 smx，整串命令过检）下为真。
- 若按工具面直接接入（tool runner 直接调 smx），内层 cmd 完全绕过 execute_command 的硬安全边界 ⇒ 新增无界 shell 能力。
- 修复方向（形态决策，非代码 bug）：并入形态=「execute_command 的注释/感知层」——保留实验用法（执行动作永远经 execute_command），工具面只暴露 wait / snapshot diff / 回执查询；或 smx 内部把 cmd 转交既有执行通道。同时修正 docstring。

### S2｜high：wait 网络谓词无 host 白名单（与宣称不符）
- L489 `socket.create_connection((args.host, args.port_open), timeout=1.0)`；L567 `--host` 无校验。docstring 称「本地端口连通性」。
- 动态实证: `wait --port-open 443 --host example.com` → **satisfied=True, detail: port_open: example.com:443**（真实外连成功）。
- 增量能力: 任意 host:port 外连探测（端口扫描面），超出既有工具面。
- 修复: --host 限 loopback（127.0.0.1/::1）或移除该参数（回归宣称语义）。

### S3｜medium-high：run_id 路径穿越 → scope 外写原语
- L200/L409/L526 `os.path.join(root,".smx/runs",args.run_id)` 未校验分隔符/`..`；collect 会向该目录写 after.json/changed.json 并**改写 receipt.json**。
- 动态实证（/tmp/smxrev 隔离环境）: `collect ../../target` → 3 个文件写入 scope 外目录，目标 receipt.json 由 bg_launch 被改写为 collect。
- 修复: run_id 白名单 `^[A-Za-z0-9._-]+$`（拒含 `/`、`\`、`..` 前缀），show/collect 入口统一校验。

### S4｜medium：快照内存物化不受 budget 约束
- L125 `sorted(os.scandir(d), key=...)` 先物化整目录再受 budget 计数；巨型目录（百万 entry）下 budget=5000 不防内存峰值。
- 修复: 迭代侧截断（如 heapq.nsmallest(budget, …) 或先取 budget×k 名再排序）。

### S5｜low：健壮性清单（不阻断，并入前顺手修）
1. fd3 假设: pass_fds=(metaf.fileno(),) 但 wrapper 硬编码 `>&3`，依赖 metaf 恰为 fd 3（当前进程成立，脆弱）→ dup 到固定 fd 或把实际 fd 号注入 wrapper。
2. PID 复用误判: collect `os.kill(pid,0)`，stale pid 被判 alive（PermissionError 也判 alive）→ 记录启动时间/cmp cmdline。
3. bg 无超时上限、collect 只报不杀: 语义如此，但工具面需要泄漏上限策略。
4. timeout 的 killpg 不及 daemonize 子进程（double-fork+setsid 逃逸进程组）。
5. file_contains 每轮全量读文件（GB×0.3s 轮询）→ cap 读取长度。
6. 文档-代码不符项（S1/S2）必须随补丁同步修正 docstring。

## 职责去重（vs 既有工具面）

| smx 面 | 既有覆盖 | 判定 |
|---|---|---|
| exec/bg 执行 + 后台管理 | execute_command（含 run_in_background/job_output/job_kill） | **重复**，不并入执行面 |
| 前后快照 diff（时间维对比） | 无（search_files/read_file 是即时态） | **不重复**，并入价值核心 |
| wait 条件谓词轮询 | 无（schedule 是定时非谓词；命令内 sleep 烧轮次且受 60s 限制） | **不重复**，并入价值核心 |
| 回执落盘/show 重放 | read_file 可读同路径文件（近似覆盖） | 冗余可选 |
| rc_chain（PIPESTATUS） | execute_command 无此粒度 | 差异化小增值 |

结论: 并入形态 = **opt-in 感知层工具（wait + snapshot diff + 回执）**，执行动作维持经 execute_command。与 S1 修复方向同一。

## 修复清单（最小集）
1. [S2] --host 白名单 loopback（1 行）
2. [S3] run_id 校验（约 3 行）
3. [S4] scandir 有界物化（约 2 行）
4. [S1] docstring 修正 + 并入形态决策（工具面不暴露 exec/bg 直执行）
5. [S5] 1/2/5 顺手修，3/4 记为已知限制

修复后建议快速回归: selftest 18/18 仍绿 + S3 PoC 变 reject。

## 修复结果（2026-09-12，用户裁决：修+感知层形态）

- smx.py 616 行，sha256 `6cdf32b76c06…`（HEAD 无 git 历史，以本 sha 为基线）
- S1: 并入形态=感知层（wait+snapshot diff+回执）；docstring 改为如实描述；自建 bash -c 通道降级为实验域用法，不进工具面
- S2: `--port-open` 强制 loopback 白名单（127.0.0.1/::1/localhost），外连 PoC `example.com:443` → exit 2 拒绝
- S3: `check_run_id` 白名单（[A-Za-z0-9_.-]，拒 `/`、`\`、`..` 片段）用于 collect/show；穿越 PoC `collect ../../target` → exit 2，target 零写入
- S4: 快照迭代有界（不物化全量 scandir），保留 entries 条数上限
- S5: 1 fd 号取自实际分配（不再假设 3）/ 2 file_contains 读取上限 8MiB / 5 collect 非法 run_id 从 NameError 崩溃改为 stderr+exit 2（顺手修好）
- 回归: selftest **18/18，exit=0**（修复版实测）；bg→collect 正常收链
- 顺手修复副作用: fd 注入经实际 fd 号，长驻任务回执不再依赖 3 号假设

## 新发现（修复验证时暴露，未修——超出本次授权清单）

**S6 [med] rc_chain 多段解析截断（既有 bug，非本次引入）**：meta 行格式 `pipe=0 0 0` 被 parse_meta 按空白切 token 后，`pipe=` 后续段被当作独立键丢弃 → 多段管道 chain 只含首段。docstring「各段退出码」宣称不成立。编辑回执谱系证明 L188-206 未被本次触碰（既有）。影响面：实验期回执中 chain 值同样只有首段（总体 rc 不受影响）。修法约 2 行（wrapper 逗号连接 + parse 按 `,` 切）；待裁决是否修。

## S6 修复结果（2026-09-12，用户授权修复）

- 修法与预估一致（2 行级）：wrapper meta 行改 `IFS=,` 连接各段（`pipe=0,1,0`），parse_meta 按 `,` 切分还原 chain（smx.py L182/L203）。
- smx.py 修复后 sha256 `b2cfc87e…`，616 行（行数不变）。
- 实证（修复版实测）：三段链 `true | false | true` → rc_chain `[0,1,0]`；五段链 `true | false | true | false | true` → rc_chain `[0,1,0,1,0]`；多段不再截断。
- 回归：selftest **18/18，exit=0**（job-378540434bfb4877aff7 实测回执）。
- docstring「各段退出码」宣称现在成立；「回执语义以首段为准」的临时说明经查未落盘于 README/smx.py/lab 冻结件及 docs/*.md，无需另行删除。
- S6 关闭。审查发现项 S1-S6 修复全部闭合；S5.3/S5.4（bg 超时上限、daemon 逃逸）仍按原裁决记为已知限制。

## 胶水层补审（2026-09-12，EVO-20260912-10818cb5 落地链要求）

- 对象: `src/llm_loop/tools/builtin/smx_perceive.py` · 315 行 · sha256 `4c343cd3…`；注册接线 factory.py L816-820 + config.py L288/L619（env `LFL_SMX_PERCEIVE`，空=默认不注册）
- 方法: 全文通读（315/315 行）+ 单测 `tests/test_smx_perceive.py`（sha `19299968…`）11/11 通过 + e2e 回执（`.smx/runs/r20260912-084413-*`、`r20260912-084645-*`）
- 核验（S1-S3 修复约束在胶水层二道校验）:
  - S1 形态: 仅四动作 wait/snapshot/diff/receipt，无执行透传；subprocess 纯 argv 列表（`[sys.executable, smx_path, "wait", "--json", …]`），无 shell=True、无命令字符串，谓词全部参数化 → 符合锁定形态
  - S2 双层: host 白名单胶水层先拒（L153-155）+ smx 冻结版内再拒 → 双层防御成立
  - S3 双层: run_id 正则 L269-270（点分段每段非空，拒 `/` `\` `..`）；receipt 只读固定 `receipt.json` 路径；snap_id 严格格式（L36/L124），快照仅落仓内 `data/smx_perceive/`
  - 行为边界: wait timeout 钳制 ≤55s + 子进程 timeout+15s 兜底；谓词超时（exit 2）视为观测结果 satisfied=false 而非工具故障
- 已知边界（不阻断，opt-in 下接受）:
  1. wait/receipt 的 `root` 为调用方任意目录——wait 会在 `root/.smx/runs/<run_id>/` 写回执 JSON（写面与 execute_command 等同，无增量）；receipt 纯只读
  2. snapshot `roots` 任意路径只读枚举（depth≤6、budget≤20000，仅路径/元数据名，不读文件内容）——与 search_files 枚举面等同
  3. importlib 动态加载 smx.py 会执行其模块级代码：冻结版模块级仅常量与函数定义（selftest 18/18 背书），无副作用
- 结论: **通过**（纯感知、opt-in 默认关、双层白名单、执行动作维持 execute_command，与演进建议锁定形态一致）
- 回归: selftest **18/18，exit=0**（job-b691a0b88 无并发复测）。备注: 09:04 一次 11/18 系并发 selftest 进程 `rm -rf $RUN` 交错所致（fixture 目录中段被清、仅存末例自建目录；冻结件 sha 自 23:23 未变、无并发不可复现），非代码回归。


