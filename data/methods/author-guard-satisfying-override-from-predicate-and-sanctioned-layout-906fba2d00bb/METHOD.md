---
method_id: author-guard-satisfying-override-from-predicate-and-sanctioned-layout-906fba2d00bb
name: author-guard-satisfying-override-from-predicate-and-sanctioned-layout
description: 服务因内部结构 guard（code-root/布局/身份 sanity check）启动失败、需要写 systemd drop-in 或 env 改动来通过它时，不试错重启、不照抄上轮方案：用上次失败的确切错误串直读 guard 谓词源码，再读同模块中官方运行路径的 env/路径构造代码（它就是被支持布局的规范），并用 ps 取一个已知健康实例的 argv/env 作参照；三者一致后用既有组件写最小 diff override（只覆盖 guard 检查的维度，不动绑定类变量），附机械验收信号（健康端点身份字段）与单文件回滚，并按谓词显式证伪继承方案。
aliases: sanity check 启动失败怎么改 systemd, drop-in override 过 code root 检查, wheel 安装过不了布局 guard, 照官方 env 构造写 PYTHONPATH override, venv 指向 checkout src 最小改动, 重启前先读 guard 判定逻辑
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7007267a-8cde-4b7c-bcc4-b677b3653671:219:3d862b7031c53656d2b0
evidence_refs: learning:learn:20a7b92c8e44
created_at: 2026-11-07T06:58:04.614092+08:00
updated_at: 2026-11-07T06:58:04.614092+08:00
---
## Trigger
常驻服务因内部 guard（布局/身份/路径 sanity check）启动失败，或用户正在写 systemd drop-in/env 以通过该 guard，且失败日志的错误文案可检索、guard 源码可读；上一轮修复方案（重装/换 release/换入口）是否满足 guard 尚未验证

## Discriminator
guard 的确切错误串能定位到谓词源码（真实判定，如控制面代码 parents[3] 下必须存在 src/<pkg>）；同一模块内官方运行路径的 env 构造代码（如 PYTHONPATH=<code_root>/src）直接展示被支持的布局；且存在一个已知健康的同构实例（ps 可取 argv/env）证明该布局在生产可用——三者同时在场时，正确配置可被推导而非试错

## Short path
- 先锚定执行面在哪个部署（本机/镜像/目标宿主）；目标机不可直达则后续经仓库源码推导 + 用户在目标机执行
- 用失败日志的确切错误串定位 guard 谓词源码并读原文，确定真实要求（哪种布局/身份），而非按报错猜测
- 在同模块找官方运行路径的 env/路径构造代码——它就是支持布局的规范，照它定的参数是 supported 配置而非 hack
- ps 取已知健康实例的 argv/env/cwd，确认它正是该布局（known-good 参照）
- 用既有组件（现有 venv + 目标 checkout/源树）写最小 diff override：只加 guard 检查的维度，不引入会改变数据/知识目录绑定的额外变量
- 定义机械验收（健康端点身份字段变为目标 sha/版本）与单文件回滚路径；按谓词对继承方案显式证伪（若其布局仍不满足谓词则明确指出不要走）

## Stop conditions
- guard 谓词、官方 env 构造、健康实例三者一致，且 override 仅覆盖 guard 检查的维度
- 验收信号可机械观察（健康端点中的身份/版本字段），回滚为单文件删除+reload+restart

## Verification
- 重启后读健康端点：身份字段（git_head/版本/display）变为目标值，证明新布局真正生效而非仅进程存活
- 删除 override + daemon-reload + restart 可完整回滚到原状态（有 Restart=always 时注意 crash-loop 风险，先确认路径再重启）
- 复查 override 内容：不含 guard 谓词未要求的绑定类变量（workspace/runtime root 等会改变持久化目录归属的项）

## Counterexamples
- 静态配置没有可读的 guard 谓词（纯文档型配置）→ 直接按文档写，三角验证无对象
- guard 失败原因是权限/资源/网络类而非布局身份类 → 读谓词不产生配置改法，应换诊断方向
- env 构造代码与 guard 来自不同版本（读的是旧 checkout 的构造器）→ 以目标运行版本源码为准重读，不能复用旧结论
- 没有任何 known-good 活实例且目标机完全不可达 → 只能给校验清单让用户先手工验证，不能给确定的 override
- 需求是换依赖集而非换代码布局 → 让 venv 指向新 src 不解决依赖差异，需独立核验依赖兼容
