---
method_id: verify-artifact-identity-before-trusting-probe-contradiction-73cb470fb725
name: verify-artifact-identity-before-trusting-probe-contradiction
description: 当针对非默认代码位置（worktree/分支/.releases 快照/venv）运行的临时探针脚本给出与权威测试套件矛盾的'惊人发现'（如疑似安全漏洞）时，先不要读代码找洞、也不要堆更多探针；先做一步机械检查：在同一解释器里打印探针实际导入模块的 __file__/解释器路径，确认探针与被审对象解析到同一 artifact。裸 python 常解析到 .releases 旧版本或 site-packages，其结果是噪音。确认错位后用 PYTHONPATH=<worktree>/src 钉住重跑；只有探针被证实执行被审代码后，其发现才可作为证据写入审查回执。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:de7f7e47-443e-42f9-9513-57ee99c8a21e:119:192af5b5e09c5b26e36a
evidence_refs: learning:learn:88ebeda162a1
created_at: 2026-10-13T03:58:12.612583+08:00
updated_at: 2026-10-13T03:58:12.612583+08:00
---
## Trigger
对 worktree/分支/release 快照等非默认代码位置运行临时验证脚本或探针，其结果与刚在同一 worktree 通过的权威测试套件矛盾，或呈现'旧代码才有的失败模式'时。

## Discriminator
矛盾时刻已可见的事实：pytest 刚在同一 worktree 通过 32 项分支测试；探针是裸 `.venv/bin/python -` 启动、未设 PYTHONPATH（pytest 靠 conftest 注入 sys.path）；失败形式恰是旧版/legacy 逻辑会拒绝的那类（`git show|tail`、`grep 'rm -rf'`、`git ls-files`）。一条机械检查即可区分'探针执行了别的代码'与'分支有洞'：打印探针实际导入模块的 `__file__`（实测解析到 `.releases/<旧sha>/src/...`，而非 worktree）。

## Short path
- 探针结果与权威套件矛盾时，先只列两个候选解释：(a) 被审代码有缺陷；(b) 探针执行的是另一份 artifact。此步禁止重读代码找洞或加码探针。
- 在同一次调用里做 artifact 身份检查：import 被测模块并打印其 __file__（必要时附 sys.executable/sys.path），与被审路径逐字比对。
- 若解析到别处（.releases/旧 sha、site-packages、主 worktree），判定该矛盾无效：显式钉环境（PYTHONPATH=<worktree>/src 或复用测试套件同款 runner）后重跑探针。
- 重跑全绿后才把探针结果作为证据写入结论/回执；若钉住后矛盾仍在，才升级为真实候选缺陷，进入代码级排查。

## Stop conditions
- 探针解析路径 == 被审 artifact 且结果与权威套件一致 → 进入裁决，停止环境排查。
- 钉住环境后矛盾复现 → 停止环境归因，按真实候选缺陷处理并上报。
- 两个通道从一开始就能证明共用同一解释器/导入路径 → 跳过身份检查，直接查代码。

## Verification
- 探针输出必须与其 import 解析路径（__file__/sys.executable）同场记录；未钉环境的探针结果不得作为分支缺陷或漏洞的证据。
- 钉住后重跑并核对预期数量（本例 22/22、输出 'probe_clean'）之后，才允许把探针结果写入审查回执。

## Counterexamples
- 探针与套件可证明共用同一解释器/导入路径（如探针本身就是同一 pytest session 的用例）→ 矛盾是真实的，应查代码而非环境。
- 导入路径已确认是被审代码，且失败形式属于套件未覆盖的真实攻击面（如新的注入形式）→ 作为真实发现上报，不得以'环境错位'搪塞。
- '权威结果'本身已过期（测试未随本次改动更新）→ 身份检查只证明探针对齐了 artifact，不证明正确性；两个通道都必须面向新 artifact 重跑后再比较。
