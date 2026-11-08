---
title: 跨机把仓库知识卡刷入 Linux 宿主 live：ssh operator@[private LAN address redacted] + quotepath=off 名单 + 门控脚本，落位即生效
scenario: "宿主 LFL 会话（bwrap 沙箱）无法操作自身 ~/.local/share/lfl 下的 live 知识目录，需要从 mirror 侧（Mac）把仓库里的 experiences/methods 卡刷入宿主生效；典型触发：publish 后代码无 diff、仅知识资产缺口的\"实际生效\"收口。"
root_cause: ""
solution: "ssh -o BatchMode=yes operator@[private LAN address redacted] 直达宿主（先探测确认目标机身份），脚本+py 落盘后 scp，ssh 'bash /tmp/x.sh' 执行；名单用 git -c core.quotepath=off diff --name-only 动态生成并做双源交叉+形态校验；按\"机制核对→基线→名单→冲突→复制→按名验证\"门控推进；生效机制=目录每次检索现扫磁盘，文件落位即生效无需重启（已在宿主 0.6.39 wheel 实证）。"
evidence: "宿主实测全门控通过：exp scanned 10→19（+9）、active 10→19、methods candidate 4→6（+2）、11/11 按名在列、/health ok；证据 evidence://v1/f6743c6de015dda0a2af86e47781e46d64face6c70e007e5bc77ea073a5bc5b1；坏名单反例见 evidence://v1/4925ea4259a0dfdf022eef07cf7f03629ef93b7e66c96a14113c017d494110ba 前一轮本地输出"
tags: [宿主, knowledge-flush, ssh, quotepath, service_control, ops]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-07T01:12:11.508625+08:00"
updated_at: "2026-11-07T01:12:11.508625+08:00"
---

背景：宿主上的 LFL 会话跑在 bwrap 沙箱里看不到 /home/operator/.local/share/lfl，但 mirror 会话（Mac）可以 ssh 到宿主替它执行。本经验记录 2026-11-07 实测有效的完整通道与三处坑。通道事实：宿主=LAN Linux 机 operator-PC（[private LAN address redacted]，x86_64，用户 operator，免密 ssh BatchMode 可用）；OrbStack ubuntu 与 Parallels 网段都不是目标。判据：存在 /home/operator/.local/share/lfl 且 127.0.0.1:8903/health 返回宿主版 web。执行姿势：①一次性脚本先落盘再执行（RULE-AI-36）；②python 逻辑写成独立 .py 文件 scp 过去，bash 脚本内不嵌任何 heredoc——安全闸硬拦"heredoc 交给解释器执行"，合规替代是 ssh 'bash /tmp/xx.sh'（不要 ssh 'bash -s' < file）；③名单必须 git -c core.quotepath=off diff --name-only 生成：默认 quotepath=true 把中文路径打成带引号八进制转义串，sed 剥不动前缀，会复制出错误文件名（本例实测踩中，门控拦截）；再加 grep -q '^"' / ^EXPERIENCE- 形态防线。edit_file 的 snapshot 契约不覆盖 .tmp 旁路目录（"snapshot 不属于当前工作区"），需要改这类文件时整文件 heredoc 重写即可。门控序列（每步失败即中止且不写状态）：机制 grep 核对 → 基线落盘+绑定目录断言 → 名单 9/2 硬校验+双源交叉 → 零冲突 → 复制（exp 平铺 cp、method 整目录 cp -R）→ 按名验证+计数 delta+/health。