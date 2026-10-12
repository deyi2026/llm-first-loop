---
method_id: preflight-tool-flags-against-declared-dependency-surface-b5efe2186940
name: preflight-tool-flags-against-declared-dependency-surface
description: 启动昂贵或后台工具调用前，若命令携带由可选插件/扩展提供的非默认旗标，先对照上下文中已可见的契约面（刚读过的依赖清单、工具 schema、先前回执）核实每个旗标的提供者是否存在。提供者缺失=可预知的 usage 拒绝，应先调整调用（去除旗标或显式安装）再启动，而不是用一次完整执行去发现契约拒绝。本episode中 pyproject dev 清单刚读毕（有 pytest-xdist、无 pytest-timeout），仍带 --timeout=300 启动后台测试，被 unrecognized arguments 拒绝后只能重跑，硬证据收集被延迟一轮。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:46fe7522-52e6-44a0-bc3c-bc78cdd27955:9:915a9ebd98fe9d5a2e47
evidence_refs: learning:learn:648122e8bd34
created_at: 2026-10-08T13:52:58.115648+08:00
updated_at: 2026-10-08T13:52:58.115648+08:00
---
## Trigger
即将启动耗时/后台工具调用，且命令含非默认旗标（尤其测试框架插件类选项如 --timeout/--cov），同时上下文中已存在可判定该旗标可用性的契约证据（依赖清单、工具帮助、回执）。

## Discriminator
启动前一步刚读到的 pyproject.toml dev 依赖仅声明 pytest 与 pytest-xdist，无 pytest-timeout；--timeout 选项由 pytest-timeout 提供，提供者未声明即不可用。同一清单里已可直接区分：已声明插件的旗标（-n/--dist）可用，未声明提供者的旗标（--timeout）必被拒绝——无需事后回执才知道。

## Short path
- 明确未知量：测试套件当前是否全绿；读 pyproject/pytest 配置确认调用约定（该步本集已完成）
- 对每个非默认旗标核对提供者：-n/--dist→pytest-xdist 已声明；--timeout→pytest-timeout 未声明
- 对未声明提供者的旗标做一次廉价核实（pytest --help / pip show）；审计场景环境不可污染，默认去除旗标
- 以精简命令单次启动后台测试并轮询回执
- 取得明确 pass/fail 汇总即停止，不做额外确认性重跑

## Stop conditions
- 后台任务回执给出明确 pass/fail 统计
- 启动前已确认旗标提供者缺失且非必需：直接以精简调用启动，不再为该旗标枚举变体或试错

## Verification
- 启动前机械判定：pytest --help | grep <flag> 或核对依赖清单，结论可复现、不依赖模型印象
- 启动后回执无 usage/unrecognized-arguments 类拒绝；本集反事实为首次启动即应成功，可省 1 次失败任务、1 轮轮询和硬证据延迟

## Counterexamples
- 清单缺失≠提供者必然缺失：插件可能是传递依赖或手动装入 venv——此时清单缺失只是'需廉价核实'的信号，须先验证再改调用，不能只凭清单否证
- 调用本身廉价、前台、幂等时，预检开销大于失败成本，直接执行即可
- 旗标必需且提供者确缺：正确动作是显式安装并记录变更；但审计类任务会改动被审环境，通常应去除旗标而非安装
- 命令不含非默认旗标，或上下文没有任何契约证据可对照时，本方法不适用，按常规启动+失败回执处理
