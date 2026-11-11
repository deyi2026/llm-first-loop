---
method_id: gate-red-after-entry-wrapper-swap-restore-implicit-env-contract-6feca4f3b198
name: gate-red-after-entry-wrapper-swap-restore-implicit-env-contract
description: 推送把 CI 门禁入口从会注入环境的包装器（如 uv run）换成自管脚本/Makefile/容器入口后，门禁出现确定性红：先用并行与串行复跑 summary 确定复现条件，串行转绿不等于已证实 flake；对可重复失败，若失败测试文件不在本次改动集、且 traceback 显示测试在子进程里裸调用工具名（隐式依赖旧包装器注入的 PATH/env），第一未知量就是『旧包装器隐性提供了什么环境契约』：本地做受控最小环境差分（正常 vs 剥离注入）复现红/绿对照，修复方向是在新入口显式恢复该契约（如前置 venv/bin），不改写测试去迁就环境。
aliases: 换了启动脚本测试就挂, 子进程裸命令在 runner 上找不到, 本地能过 CI 却挂的环境差异定位, 测试对 PATH 的隐性依赖被暴露, 串行复跑确认复现条件再查根因
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:3079:394b20f85131362f8a43
evidence_refs: learning:learn:f1eb87b676a9
created_at: 2026-11-11T08:12:35.457083+08:00
updated_at: 2026-11-11T10:23:44.117919+08:00
---
## Trigger
CI 门禁在一条改动了测试启动/入口包装器（workflow、门禁脚本、Makefile、容器 entrypoint）的推送后报红，且失败的测试文件不在本次推送改动集中。

## Discriminator
三个当时即可见的事实同时成立：①失败日志含两段 pytest summary（全量并行 N failed、串行补集 M failed 且 M<N），流水线提供两种负载条件的观测；②git diff 显示改动集只有入口/infra 文件；③真红测试的 traceback 打印出其子进程命令是裸工具名（如 pytest --version），隐式依赖旧包装器注入的 PATH/env。

## Short path
- 一次带过滤的 --log-failed（grep summary 与 FAILED 行）同时拿到并行/串行两段失败集：交集为串行也可复现的失败，差集为仅并行观察到的失败；两组均需归因，不能仅凭串行转绿判为 flake。
- git diff 推送范围：失败测试文件未被改而入口包装器被改 → 嫌疑从产品代码转移到执行环境契约差。
- 读真红 traceback 中的子进程调用点，确认是裸命令、依赖 PATH/env 而非代码逻辑。
- 本地受控环境差分：正常环境跑过、剥离可疑注入（干净 PATH）复现 CI 同款断言红、改用显式环境入口（venv 绝对路径）又过 → 契约即该注入。
- 核对新入口确实缺少该注入 → 修复=在包装器里显式恢复注入，保持测试语义不动；其余并行失败分别检查文件锁、事件顺序和性能测量负载，不将真实竞态归为环境噪声。

## Stop conditions
- 受控差分三格对照已闭合（正常绿/剥离红/显式注入绿）且新入口确认缺注入 → 根因已定，停止扩散，输出一行修复。
- 剥离环境后本地仍复现不了 CI 红 → 契约不在 PATH/env，放弃本假设，回到平台差异或日志级排查。

## Verification
- 对照实验三格齐全且只有『剥离注入』一格与 CI 同断言失败，结论才成立。
- 修复后验证：新入口补注入，同一测试在干净环境转绿；其余仅并行失败不因本次 PATH 修复被声称修好；修复真实竞态后按原并行条件验证。

## Counterexamples
- 失败测试文件本身就在推送改动集里 → 普通 regression，直接查产品代码，不套环境契约。
- 失败只在并行全量出现、串行复跑已全过 → 仍可能是真实读写竞态或测试缺少同步。实测 grant 在持排他锁截断 JSON 时，无锁读取会失败；串行通过不能排除该缺陷。
- CI 报 ModuleNotFoundError 类依赖缺失 → 修依赖安装/镜像，PATH 前置不是主因。
- 本地正常/剥离环境实验无差异 → 旧包装器与测试间不存在隐式注入关系，方法不适用。

## Maintenance correction
2026-11-11：依据 GitHub CI run 42924222973 与修复提交 91d15c230，纠正“串行绿即可判 flake”的旧结论。代码回归已覆盖持锁截断期间的读取，原性能阈值保持不变。
