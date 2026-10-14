---
method_id: pin-loaded-artifact-identity-before-repro-adjudication-9c1fc1f8d116
name: pin-loaded-artifact-identity-before-repro-adjudication
description: 复现/验证针对“工作区未提交改动”的行为报告时，裸解释器、pytest、脚本可能各自解析到不同代码副本（editable 安装、release 快照、shell 注入 PYTHONPATH、pyproject pythonpath）。首次复现命令必须同时打印 module.__file__/版本，把结果绑定到实际加载的 artifact；复现结果与外部报告矛盾时，首选假设是“加载了另一份代码”而非“报告不成立”，用显式路径变量做单变量重跑裁决，并同样核查测试运行器解析的是哪份代码。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:43966c4f-fe71-4779-a054-72a945697fa7:969:2687a8dc3aa41eb7a691
evidence_refs: learning:learn:4d28abfa2adf
created_at: 2026-10-13T23:27:39.034071+08:00
updated_at: 2026-10-13T23:27:39.034071+08:00
---
## Trigger
需要独立复现一个针对未提交工作区改动（working-tree diff）的行为报告（外部评审反例、缺陷复现、测试证据），且环境存在多副本代码层：venv editable 安装、发布/快照目录、shell 注入的 PYTHONPATH、或测试工具自带的 import 路径配置。

## Discriminator
被验证的行为只存在于未提交的工作区改动中（报告已声明 HEAD 与未提交修改），而当前解释器的模块解析路径未经证实指向工作区源码——因此任何未绑定 __file__ 的复现结果都无法裁决矛盾；“复现结果与报告矛盾”这一事实本身，是“两方测的是不同代码副本”的首发证据，而非报告错误的证据。

## Short path
- 复现命令内置 provenance 钉扎：import 目标模块后先打印 __file__ 与版本常量，再运行反例用例，一次调用同时产出行为结果与该结果属于哪份代码。
- 若 __file__ 指向快照/发布目录而非工作区源码 → 判定副本不一致，用显式 PYTHONPATH=src（或等价单变量）重跑；反例裁决只以钉扎后的运行结果为准。
- 核查其他证据生产者（pytest/CI 脚本）解析哪份代码：读 pyproject 的 pythonpath/addopts 或用探针测试打印实际导入路径，确认“测试全绿”是否真的测了目标 diff。
- 环境事实链闭合（哪份代码被谁加载均已确认）后才下验证裁决，再进入修复、红绿回归与精确提交。
- 修复后的验证同样在钉扎路径下运行，提交说明中留档解析证据。

## Stop conditions
- 反例裁决所依据的每一次运行都已绑定加载 artifact（__file__ 或运行器路径解析证据）。
- 测试证据的代码来源已确认覆盖目标 diff，不存在“跑在旧副本上的绿灯”被误用。
- 复现矛盾已被“哪份代码被加载”完全解释，无剩余歧义即可停止环境排查。

## Verification
- 同一命令内输出 __file__ + 版本 + 行为结果，三者一致并留档。
- 对 pytest 用一次探针（临时测试打印被导入模块路径）确认其解析目标。
- 裁决前后的两次运行仅差一个显式路径变量，构成单变量对照。

## Counterexamples
- 单副本环境（干净安装、无 editable/快照/PYTHONPATH 注入）下直接复现即可，钉扎属多余仪式。
- 验证目标本来就是已部署快照/生产版本的行为时，加载快照是正确的，强制 PYTHONPATH=src 反而测错对象。
- 复现结果与报告一致且本会话已有钉扎记录时，无需每次重复钉扎。
