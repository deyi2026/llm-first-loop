---
method_id: acceptance-field-track-derivation-then-probe-change-channel-79b74990e493
name: acceptance-field-track-derivation-then-probe-change-channel
description: 部署覆盖类改动（如 systemd drop-in 用环境变量换代码源）后，健康/状态端点的身份或版本字段与预期不符（该显示 commit 却为空、版本停在旧号）时，先读该字段的计算代码确认推导输入：字段若从 binding code_root 而非实际 import 路径推导，则结构上无法见证此类改动，空值是常态而非故障；字段恰好相符也可能不具区分度（版本常量未 bump）。决定性验收放在改动的交付通道端点：查进程 environ 确认注入的环境变量，再用同一解释器加该变量解析目标模块 __file__，两处一致即定论，不再反复用展示字段确认。
aliases: 重启后版本还是旧的是不是白部署了, 服务到底加载的哪份代码, 怎么确认进程在用我覆盖的代码, 部署完health字段空着正常吗, 状态页身份字段能当上线判据吗
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7007267a-8cde-4b7c-bcc4-b677b3653671:243:b0b33061ac0794c7d2ee
evidence_refs: learning:learn:dfe19c5d7edb
created_at: 2026-11-07T08:33:42.662603+08:00
updated_at: 2026-11-07T08:33:42.662603+08:00
---
## Trigger
常驻服务经环境注入/路径覆盖等方式切换代码源后，健康或状态端点的身份/版本字段与部署预期不符（该显示 commit 却为空、版本停在旧号），需要判定新代码是否实际生效

## Discriminator
回执同时暴露了字段推导输入的痕迹（git_available:false、build 全空）与进程真实启动事实（CGroup 中解释器来自另一 venv 路径）；两者不一致即提示字段并不从实际加载的代码推导。再取一条同型环境对照（另一实例 /health 显示 git_head 且其 binding code_root 指向自己的 release 目录）即可确认字段追踪 code_root 而非 import path，随后直读字段计算模块定案

## Short path
- 把验收问题改写为『改动经由哪条通道进入运行进程』（本例：drop-in 环境变量→解释器模块解析），而不是『状态字段何时变好看』
- 读状态字段的计算代码（通常一个小模块），列出其确切输入；判定该输入是否包含改动的交付通道——不包含则字段对本次改动结构性失明，空值是预期而非故障
- 对『看似相符』的字段检查区分度：目标版本与备选版本制品可能共用未 bump 的常量，相等不能定论
- 在通道端点做一次决定性探针：/proc/<MainPID>/environ 里确认注入变量存在；再用 live 解释器加该变量 import 目标模块并打印 __file__
- 探针两端闭合即出结论并停止，不再围绕展示字段继续采集证据或反复重启确认

## Stop conditions
- 通道两端证据闭合：进程环境含指向部署 checkout 的注入变量，且同一解释器在该变量下把目标模块解析到部署目录而非 site-packages
- 或字段计算代码证明其输入恰为交付通道本身，此时字段值即可直接作验收
- 判明字段与改动无因果后，不再围绕该字段继续解读或补证

## Verification
- /proc/<MainPID>/environ 中存在指向部署代码目录的注入环境变量（如 PYTHONPATH）
- live venv 的同一解释器在该变量下执行 import 目标模块，__file__ 指向部署 checkout 而非 wheel 安装位置
- 可选佐证：对比目标版本与备选版本制品内的同一版本常量，确认该字段是否具备区分度

## Counterexamples
- 字段推导输入就是交付通道（服务直接从新 release 目录启动，code_root 即新代码）→ 字段本身合格，直接用它验收，无需另设探针
- 字段与部署目标无因果（纯展示性版本号或装饰信息）→ 不必读其推导代码，直接忽略该字段
- 无 /proc 访问且无法用 live 解释器执行命令 → 退回制品常量比对等次级佐证，但只能标『未定论』，不能当验收结论
