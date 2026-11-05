---
method_id: out-of-tree-verify-script-pin-import-to-repo-tree-663c30f3008a
name: out-of-tree-verify-script-pin-import-to-repo-tree
description: 在仓库外（如 /tmp）写临时脚本、用 import 验证刚修改过的 src 布局仓库源码时，第一个未知量不是『补丁对不对』而是『脚本 import 到了哪份包』：环境里同名包的已安装旧副本会静默遮蔽仓库树，症状是新增字段/符号缺失（KeyError/AttributeError）而非 import 失败。规则：验证首跑就固定解析——cd 仓库 + PYTHONPATH=src + 仓库 venv 的 python，或把验证并入仓库 pytest；一旦出现『补丁回执确认已落盘，但 import 到的模块缺新符号』的矛盾，只查 import 解析（打印模块 __file__），不重打补丁、不全量重读文件。
aliases: 改了代码一跑 KeyError 新字段, tmp 脚本 import 到旧包, 验证脚本 import 错副本, site-packages 遮住 src, 刚打的补丁验证不生效
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:d0e6ba0c-dfdb-4a7e-b110-850f0ae238a6:1095:12962a5bd503b29c7238
evidence_refs: learning:learn:cff0195cfd34
created_at: 2026-11-05T13:34:16.342934+08:00
updated_at: 2026-11-05T13:34:16.342934+08:00
---
## Trigger
用放在仓库外（如 /tmp）的临时脚本通过 import 验证刚修改过的 src 布局仓库源码，且运行环境（venv/site-packages）里可能装有同名包的旧副本

## Discriminator
两条当时已知事实的组合即可提前锁定：①补丁回执已确认新代码写进了仓库文件；②验证脚本位于仓库外，sys.path[0] 不含仓库 src——import 会静默解析到已安装旧副本；失败签名是新增字段/符号缺失（KeyError/AttributeError）而非 import 报错

## Short path
- 修改仓库源码的载荷用『先落盘再执行』姿势（cat > /tmp/x.py 后 python3 -I 执行），规避 here-doc 直灌解释器类硬阻断
- 验证脚本第一次运行就把 import 解析固定到仓库树：cd 仓库 && PYTHONPATH=src .venv/bin/python /tmp/verify.py，或直接并入仓库 pytest（其路径解析已正确）
- 若已发生 KeyError 新字段：对比『补丁回执（文件已含新符号）』与『import 到的模块缺新符号』，矛盾 ⇒ 只诊断 import 解析，不重打补丁、不重读整文件
- 脚本内 print(目标模块 __file__) 指向仓库 src 即证明解析正确，读到新字段空态/计数符合设计后停止该未知量

## Stop conditions
- 模块 __file__ 指向仓库 src 路径且新字段行为（空态可用性位、计数）符合设计
- 路径固定后『新增符号缺失』签名消失，不再对同一文件重复打补丁或全量重读

## Verification
- 验证脚本打印目标模块 __file__，应为仓库 src 路径而非 site-packages
- 空态与有数据两种 fixtures 下新字段/可用性位输出符合设计（本集：help_available=false 且 degraded 逐条透出原因）
- 仓库单测（pytest）通过，作为路径解析正确的旁证

## Counterexamples
- 目的就是验证已安装/部署产物（生产实际运行的副本）时，必须用安装副本，固定到仓库树反而验证错对象
- import 直接 ModuleNotFoundError 的环境缺失问题：属先定位项目权威解释器/venv，路径固定解决不了缺依赖
- 脚本不 import 仓库包（纯标准库文本处理）时，脚本位置无关
- editable 安装已指向仓库树时普通 venv python 本来就解析正确，该失败签名不会出现
