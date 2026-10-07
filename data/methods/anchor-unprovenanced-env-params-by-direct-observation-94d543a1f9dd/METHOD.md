---
method_id: anchor-unprovenanced-env-params-by-direct-observation-94d543a1f9dd
name: anchor-unprovenanced-env-params-by-direct-observation
description: 当工具需要环境锚定参数（workdir/仓库根/venv 路径等）而准备填入的取值在当前上下文任何已观察证据中都无出处时，先用一次直接观察（pwd、ls、git rev-parse --show-toplevel）锚定真实环境再调用，不要猜'看起来合理'的路径。参数错误回执后同理：只做一次权威锚定读，不做目录枚举。锚定后用当前工具输出复核用户前提（如 lint 计数与构成），再仅对可能对应真缺陷的规则项做单次读码裁决。适用信号：参数值是凭印象拼出的默认路径、失败回执指出目录无效、需要重新定位仓库根。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ba2daf39-ade3-4308-855e-bf3018c00381:264:ad4db9a3e8726e39c13c
evidence_refs: learning:learn:3cd306e5df46
created_at: 2026-10-06T21:33:37.611032+08:00
updated_at: 2026-10-06T21:33:37.611032+08:00
---
## Trigger
即将调用的工具/命令需要环境锚定参数（workdir、仓库根、venv/config 路径），而该取值在当前上下文的任何用户消息、回执或证据中都没有出处，只能靠猜；或上一条回执刚报'参数错误/目录无效'需要重新定位。

## Discriminator
调用前自查：这个参数值在任何已观察证据中有出处吗？本集调用前没有任何 artifact 提到 /workspace/... 路径（助手事后自述'workdir 猜错了'即零出处的直接确认）；而真实值可通过一次零成本观察（pwd; ls; git rev-parse --show-toplevel）直接获得。零出处 + 可直接观察 ⇒ 必须先观察再调用。

## Short path
- 调用前对每个环境锚定参数问：取值出处是用户消息/先前回执/配置中的哪一个？有出处则直接用，不二次怀疑。
- 无出处时，先跑一次权威锚定观察（pwd + ls 或 git rev-parse --show-toplevel），解决唯一未知量：当前真实工作根是什么。
- 用一条针对性 provenance 探测确认该根就是目标仓库（如 git log 存在同主题提交，本集为 337e2855f 的 ruff 修复记录），不做目录枚举。
- 在锚定根上跑真实任务命令（只读 ruff check），用当前输出复核用户前提（26 处、规则构成一致）。
- 仅对规则名可能对应真缺陷的项（F811）读一次定义面+关键使用点做语义裁决，然后停止。

## Stop conditions
- 锚定根已确认且任务命令输出与用户前提一致（计数/构成吻合）⇒ 停止定位，进入判断。
- 疑似真缺陷项已由定义+使用点核实语义 ⇒ 停止继续取证。
- 定位阶段最多一次锚定观察 + 一条针对性确认，不扩展成目录/全库枚举。

## Verification
- 重跑的规则构成（E402×9/I001×4/SIM105×3/.../F811×1/F401×1，共 26）与用户报告吻合 ⇒ 证明锚定的仓库正确。
- 被标记缺陷（attestation.py:319 F811）经读取 :310 字段与 :319 classmethod 定义及 :316/:326 使用点后确认运行语义无冲突，而非仅凭规则名下结论。

## Counterexamples
- 用户消息或任务元数据已显式给出路径（有出处）⇒ 直接使用该路径；即使失败，失败回执本身成为新锚点，而不是再猜一个。
- 先前工具回执/错误信息已打印出有效绝对路径 ⇒ 沿用该被点名路径，无需再 pwd。
- 环境无观察手段（无 shell、纯远程 API 且文档声明固定挂载）⇒ 文档即出处，本方法不适用。
- 任务目标本身就是'找出哪个目录是仓库'（定位即任务）⇒ 此时枚举合法，不适用本方法。
