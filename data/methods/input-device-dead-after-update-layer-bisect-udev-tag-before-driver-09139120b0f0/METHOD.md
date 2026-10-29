---
method_id: input-device-dead-after-update-layer-bisect-udev-tag-before-driver-09139120b0f0
name: input-device-dead-after-update-layer-bisect-udev-tag-before-driver
description: Linux/桌面环境更新后内置输入设备（触摸板等）失效时，先做一次只读探针在协议栈分层二分：内核 evdev 是否注册该设备 vs libinput 是否列出它。内核有而 libinput 无 ⇒ 断点在 udev 标签/合成器准入层而非驱动；LIBINPUT_IGNORE_DEVICE=1 ⇒ grep 规则目录定位具体文件，udevadm test 复现命中；修复前用 dpkg -S 归属 + mtime 对照 apt 日志判断是包配置还是更新进程写出的野文件，决定改名回滚策略并预警再现。搜索空间从『驱动/内核/回滚/udev/合成器』多分支缩为单层单文件，避免上来就重装驱动或换内核。
aliases: 更新完触摸板没反应了, 升级后触摸板失灵怎么修, libinput 看不到触摸板, 触摸板被 udev 规则屏蔽, Deepin 升级后触摸板不能用, 输入设备失效分层排查
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ce8b88af-7349-4903-91ab-b37a329e0489:967:6296dc2c03a27cd76b82
evidence_refs: learning:learn:dc32f32d39c2
created_at: 2026-10-29T00:26:27.582887+08:00
updated_at: 2026-10-29T00:26:27.582887+08:00
---
## Trigger
Linux 或桌面环境（Deepin/Ubuntu 系）更新或升级后，内置输入设备（触摸板/指点杆）失效需修复；目标机可能远程且用户未指明是哪台；直觉解（重装驱动、换内核、回滚系统）尚未执行

## Discriminator
一次只读探针即可二分：/proc/bus/input/devices 列出该设备（含 eventN handler，驱动注册正常）而 libinput list-devices 不列它 ⇒ 失效在 udev 标签/准入层而非内核驱动。进一步 udevadm info --query=property 出现 LIBINPUT_IGNORE_DEVICE=1 ⇒ 直接把候选缩到设置它的规则文件；dpkg -S 无归属且 mtime 落在 apt 更新窗口内 ⇒ 是更新进程写出的野文件而非包配置，修复方式不同（改名可回滚、可能再现）

## Short path
- 目标机未指明时，用 ~/.ssh/config 与 known_hosts 的既有 provenance 列候选主机，一次 ping/SSH 探活确认在线与可登录用户，不扫全网
- 单次 SSH 只读体检同时取三件事：/proc/bus/input/devices、libinput list-devices、会话类型——回答『哪一层丢的设备』
- 内核有、libinput 无 ⇒ udevadm info 查该 event 节点属性，回答『是否存在准入层标签或权限问题』
- 出现 LIBINPUT_IGNORE_DEVICE=1 ⇒ grep /etc/udev 与 /lib/udev 规则目录找设置者，回答『哪条规则干的』
- udevadm test 复现该规则确实命中此节点；dpkg -S 查归属 + mtime 对照 apt/dpkg 日志，回答『包配置还是更新进程写的野文件』：野文件⇒改名禁用（回滚一行）、预警可能再现；包配置⇒走官方配置开关或提 bug
- 修复后 libinput list-devices 出现该设备 + 用户实际移动验证；已列出但光标不动则注销重登让合成器重扫

## Stop conditions
- 内核 /proc/bus/input/devices 里根本没有该设备 ⇒ 转驱动/firmware/内核层（dmesg、i2c-hid），不继续 udev 路径
- libinput 已列出设备但光标不动 ⇒ 转合成器/会话/用户配置层，停止规则排查
- 规则文件 dpkg -S 命中真实包归属 ⇒ 不直接改名，改查包的配置开关或上游 bug
- udev 属性无任何忽略标签且权限正常 ⇒ 断点在合成器侧，udev 路径终止

## Verification
- udevadm test 对具体 event 节点的输出确实回显该规则赋值 LIBINPUT_IGNORE_DEVICE=1，证明因果而非仅时间相关
- 修复后 libinput list-devices 列出该触摸板，用户确认可移动；仍不动则注销重登一次再验
- 野文件结论有双证据：dpkg -S 无归属回执 + mtime 落在 apt/dpkg 日志记录的更新窗口内

## Counterexamples
- 设备在内核层就消失（i2c/hid probe 失败、BIOS 禁用）⇒ 第一步二分即改判驱动/硬件层，udev 排查不适用
- 触摸板在登录界面可用、登录进桌面后失效 ⇒ 用户级桌面配置或触摸板开关，非系统 udev 规则
- 目标机就是当前本机、无远程歧义 ⇒ 跳过主机发现，直接进入分层探针
- 失效与更新无关（进水、排线松动等物理原因）⇒ 软件各层探针均正常但设备从未注册，需硬件排查
