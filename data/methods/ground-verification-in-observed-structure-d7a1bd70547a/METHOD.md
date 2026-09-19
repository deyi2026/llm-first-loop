---
method_id: ground-verification-in-observed-structure-d7a1bd70547a
name: ground-verification-in-observed-structure
description: 执行验证命令（pytest 指定测试文件、直接构造类做 E2E）前，把命令中每个来自记忆推测的成分（文件路径、构造函数签名）先用一次廉价的结构观察钉死：ls 测试目录一级、grep 目标类的 def __init__（模块路径在补丁头里已知）。收到 file-not-found / TypeError 这类接口不匹配失败时，把它当作'去观察结构'的信号，而不是换一个猜法重试或扩大到全树枚举（会把 evals 产物等噪声扫进来）。服务生效性只由 service.git_head 与修复 commit 的对比判定，避免对进程状态重复轮询。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:158:d0090ad18e86915ed20c
evidence_refs: learning:learn:9ef059808850
created_at: 2026-09-18T14:27:26.191728+00:00
updated_at: 2026-09-18T14:27:26.191728+00:00
---
## Trigger
要在当前仓库执行验证命令（跑相关测试、构造对象对真实数据做端到端查询），而命令中的测试文件路径或 API 构造签名来自记忆/惯例推测，尚未在本仓库实际观察到

## Discriminator
接口不匹配类失败本身加上一次廉价观察即可收敛：ls tests/ 一级即可见子目录布局（关键词 grep 为空恰说明顶层无匹配文件，测试必在子目录）；目标类的 def __init__ 就在刚打过补丁、路径已知的同一模块文件里。这些当时已可见的事实把'全树任意位置/任意 kwargs'缩到一个具体文件与一份真实签名

## Short path
- 明确待验证断言与最小载体：修复是否生效 = 相关单测全绿 + 真实数据 E2E 命中
- 执行前对每个推测成分做一次观察：ls 测试目录一级拿真实布局；grep 目标类 def __init__ 拿真实签名（模块路径来自补丁头，已知）
- 用观察到的确切路径/签名执行 pytest 与 E2E 查询，预期一次成功而非猜错再修
- 验证通过后立即 commit 固化，再以 process_versions 中 service.git_head 与修复 commit 的对比判定运行态是否生效
- git_head 不含修复 commit 则结论为'未生效'，转向 publish+restart 建议并停止；已验证的事实不再重复轮询

## Stop conditions
- 相关单测通过且 E2E 在真实数据上命中预期查询
- 服务进程记录的 git_head 已包含修复 commit，或已明确移交 operator 执行 publish+restart

## Verification
- pytest 使用的文件路径来自刚做的目录观察而非猜测，且全绿
- E2E 构造调用的 kwargs 与源码 def __init__ 逐字一致
- 生效性结论引用 service.git_head 与修复 commit 的显式对比

## Counterexamples
- 路径/签名在本次会话已被验证（刚成功跑过同一测试文件）时，无需再观察，直接复用
- 调用的是稳定公共 API（标准库/文档化 SDK）时可直接写，不必读源码签名
- 失败是瞬态网络/超时而非接口不匹配时，重读结构无信息量，应重试或换通道
- 仓库极大且结构完全未知时，git ls-files 类索引查询比逐级 ls 更合适——方法要求最廉价的结构观察，不限定具体手段
