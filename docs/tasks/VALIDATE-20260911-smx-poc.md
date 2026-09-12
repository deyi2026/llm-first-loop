# 验证计划：smx shell 域语义化 PoC（阶段一/二/三已完成 2026-09-12）

- 设计依据：`docs/DESIGN-20260911-semantic-manipulation-framework.md`（P1-P5 / 四契约 / SLA）
- 实现：`tools/smx/smx.py`（585 行，单文件，零第三方依赖）+ `tools/smx/README.md`
- 拷问记录：grill_me 返回空模板，实质拷问为模型自答推演（见 2026-09-11 会话），三处修正已被用户确认
- 阶段二协议冻结件：`tools/smx/lab/`（fixture/判定器/编排器/指标口径/配置卡，2026-09-11 闸门 0）

## 阶段一：技术原型（已完成，2026-09-11）

已验证事实（本机实测，回执可 show 重放）：
1. 管道退出码链：`ls /no/such | head -3` → `rc=0 chain=[1]`（旧 shell 只报 0，痛点①消除）
2. fs 变更 diff：4 变更命令回执 `+demo +demo/b.txt ~root`，无需重跑 ls（痛点②消除，净状态语义）
3. wait 一等动作：file_exists/gone/contains、port_open；超时 exit=2
4. bg/collect：运行态禁 diff；终态时间窗 diff（net_state_since_launch）+ 完整性校验
5. budget 截断：`--budget 8` 下 truncated=True 显式标注，不静默
6. 快照开销（H4 spot）：2.8ms/千条目；n=3000 → 8.4ms；真实仓库 depth2 → 17ms（冷缓存）

已知限制（如实进 README）：净状态语义不显形窗口内瞬时变化；rc_chain 只覆盖最后管道；
exit/exec/覆盖 trap 时 meta_missing；scope 外为启发式非完整标注。

## 阶段二：效益对照（已完成 2026-09-12；结论边界预先写死，防自证）

### 对照组方案（dsh_task，已获用户确认）

同一任务集 T1..Tn（5-10 个真实文件操作任务，脚本化下发），两种配置各跑一遍：
- A 组（control）：任务卡只允许 execute_command（裸 shell）
- B 组（treatment）：任务卡允许 execute_command 调 smx

dsh_task 为隔离会话、不继承本会话历史，是干净实验容器。
统计口径：每任务轮数、重感知调用数（重跑 ls/cat/stat/ps 类）、wait 相关任务的 sleep+重试轮数、错误恢复轮数。

### 假设与预设结论边界

- H1（diff 减少重感知）：结论限「方向性观察」。n<10 的被试内对照无统计功效，只报告方向与个案。
- H2（wait 一等动作减少轮次）：同上，方向性观察；同时报告失败率不升。
- H3（断言外包降低错误率）：**预设 insufficient 出口**——若任务集中未出现模型自行解析输出出错的案例，
  结论记 insufficient（无法检验），不得因「没有错误」推断「更可靠」。
- H4（诚实成本）：阶段一 spot 数据已达标（<200ms 量级），阶段二补不同规模/深度矩阵与真实仓库常态数据。

### 任务集草案（阶段二开始时冻结）

T1 给定目录统计 .md 文件数并写入 report.txt；T2 修复一个 failing 测试（改文件+重跑）；
T3 等待某进程写完 sentinel 再读取其输出；T4 批量重命名+验证；T5 构建小项目+验证产物出现；
T6 后台启动长任务并在完成时汇报副作用。要求：每任务有客观可判定的成功条件。

### 结果（2026-09-12；全量数据与边界应用见 `docs/SMX-STAGE2-RESULT-v1.md`）

12/12 run 判定 PASS；有效性闸门过（B 组采用 4/6=66.7%≥50%，treatment-absent 2/6<3/6）。预写死边界下：H1 方向性支持（3/4 有效对重感知降 15–56%，T3 持平个案）；H2 弱/混合（T6 轮次 10→7，T3 睡眠消除但轮次持平，T1 反升）；H3 insufficient（两臂 0 错误，天花板效应）；同报失败率 0→0。被试 n=1、B 卡附录混杂因子、n=4 有效对无功效——均已写入报告 Limitations，不外推。阶段三裁决待用户。

## 阶段三裁决点（阶段二数据后再议）

1. smx 是否并入 LFL 工具面（设计文档 §9 问题 5）：以 B 组行为差异与回执引用率为证据。
2. R2（进程卡片/job_id 语义体系）是否立项：与浏览器 DOM 追踪同构，单独一轮。
3. rc_chain 的推广（每管道段捕获）技术上可行（fd3 旁路已验证），是否值得做取决于 H3 方向。

## 阶段三裁决（2026-09-12，用户确认；拷问六问自答推演见同日会话，grill_me 模板未渲染）

1. **smx 并入 LFL 工具面：并入（opt-in，非默认注入）**。
   - 并入理由（拷问后降格）：成本面直接改善（重感知即工具调用+输出 token 消耗，T1 16→6 为直接成本下降）＋同报无损害（0→0）＋opt-in 可逆。不以"H1 因果成立"为宣称（重感知↓未传导到轮次/错误率，如实不外推）。
   - 不等实验③（③降为可选，见下）；`smx show` 回执重放不并入（12 run 全场 0 采用）。
   - **Blocking 条件**：安全审查通过（shell 语义封装=路径/glob/diff 注入面，583 行原型未过审查）＋与 execute_command/search_files 职责去重。审查不过不并入。
2. **R2（进程卡片/job_id 语义）立项：暂缓，写死复查线**——生产并入后 30 天日志内 ≥3 次完整 bg→wait→collect 使用且收益可量化 → 立项，否则不立项。无窗口/阈值的"再观察"视为不可执行。
3. **rc_chain 推广：暂缓=默认不做**。除非未来出现 A 臂非零错误率的任务域（解锁 H3 检验前提）。
4. **实验③（安慰剂卡）：可选，不前置**。仅当需要把 H1 宣称升级为"剥离附录混杂后仍成立"时才跑；多数结果不改变点 1 决策（若附录解释全部效应，opt-in 无害工具仍可留，变的只是宣称强度）。

## Blocking 条件审查结果（2026-09-12，审查报告 tools/smx/REVIEW-20260912-security.md sha 553386ca）

**As-is 不通过**；修复面小，方向不变：

- **S1 blocking**：L314 `Popen(["bash","-c",…])` 自建执行通道——并入工具面即绕过 execute_command 硬安全边界；docstring「安全边界完全继承 execute_command」对代码不成立（仅实验用法成立）。并入形态修正为**感知层工具（wait+snapshot diff+回执），执行动作维持经 execute_command**，执行面与 run_in_background/job_output/job_kill 职责重复不并入。
- **S2 high**：`wait --host` 无白名单，动态实证外连 example.com:443 成功（docstring 称仅本地端口）。修复：限 loopback。
- **S3 medium-high**：run_id 路径穿越，动态 PoC `collect ../../target` 向 scope 外写 3 文件并改写目标回执。修复：run_id 白名单。
- **S4 medium**：`sorted(os.scandir)` 全量物化，budget 不防内存峰值。修复：有界迭代。
- S5 健壮性清单（fd3 假设/PID 复用/daemon 逃逸/file_contains 全量读）不阻断，并入前顺手修。

修复后回归：selftest 18/18 仍绿 + S3 PoC 变 reject。修复完成前，点 1 的并入保持冻结。

## 修复完成与解冻（2026-09-12，用户裁决「修+感知层形态」）

- smx.py 修复落盘：616 行，sha256 `6cdf32b7…`（S1 形态决策 + S2 loopback 白名单 + S3 run_id 白名单 + S4 有界迭代 + S5 三项顺手修，详见 REVIEW 文档「修复结果」节，报告 sha `bc4530e7`）。
- 回归实测：selftest **18/18，exit=0**；S2 外连 PoC 拒绝（exit 2）；S3 穿越 PoC 拒绝（exit 2，scope 外零写入）；bg→collect 链路正常。
- **点 1 并入解冻**：opt-in 感知层工具（wait + snapshot diff + 回执），执行动作经 execute_command。
- 遗留（不阻断并入，待裁决）：**S6 既有 bug**——rc_chain 多段管道解析截断（`pipe=0 0 0` 按空白切 token，只留首段）；实验期回执同样只含首段，总体 rc 不受影响；修法约 2 行。若修，并入前回执语义以「首段」为准的说明需同步删除。

## S6 修复补记（2026-09-12，用户裁决：修）

- smx.py 修复落盘：616 行，sha256 `b2cfc87e…`（wrapper `IFS=,` 连接 + parse 按 `,` 切分，2 行级；详见 REVIEW 文档「S6 修复结果」节）。
- 实证（修复版实测）：三段链 `true | false | true` → rc_chain `[0,1,0]`；五段链 `true | false | true | false | true` → `[0,1,0,1,0]`（meta `pipe=0,1,0,1,0`）。
- 回归：selftest **18/18，exit=0**（job-378540434bfb4877aff7 实测回执）。
- 「首段为准」说明经查未落盘于任何实现/文档件，无需删除；rc_chain 现如实覆盖全部管道段。
- S6 关闭。并入（opt-in 感知层）无遗留未修审查项；S5.3/S5.4 仍按原裁决记为已知限制。
