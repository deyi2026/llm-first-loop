---
title: SWE-bench 官方 harness 本地评测（OrbStack）：平台 pull + numpy repr 数据格式 + 容器网络语义
scenario: 需要在本地（macOS arm64 / OrbStack）跑 SWE-bench 官方 harness 评测时。
root_cause: SWE-bench 官方评测在 macOS arm64 + HF 缓存权限受限环境下的 4 个坑：平台不匹配、数据格式特殊、容器网络语义、缓存权限。
solution: "SWE-bench 官方 harness 本地评测四步：① 数据集：HF 缓存权限问题 → 实例数据转 Dataset.save_to_disk('/tmp/swe_local/<repo>/test') → harness -d 指向本地路径（load_from_disk 自动识别）；② 平台：swebench 官方镜像仅 x86_64 → 改 docker_build.py 的 client.images.pull() 加 platform=test_spec.platform（linux/x86_64，OrbStack Rosetta 模拟）；③ 数据格式：F2P/P2P 可能是 numpy array repr（['a' 'b' 'c']）→ 用 re.findall(r\"'([^']*)'\", v) 提取（ast.literal_eval 会静默解析成单拼接串致假失败）；④ 结果解读：容器网络通但连接类 P2P 测试（连不可达地址）在容器语义下可能假失败——以 F2P 全过为修复真相，P2P 失败查具体测试名判断是否环境性。报告落盘 docs/analysis/SWE-bench-official-summary_20260818.md。"
evidence: 2026-08-17/18 SWE-bench 官方 harness 评测（OrbStack Docker）：pylint 8/10、sympy 27/27（修复 numpy repr 后）、requests 4/8、pytest 19/19（前会话），合计 58/64。关键：① arm64 平台 pull 加 platform 参数解决镜像拉取；② sympy 数据 F2P/P2P 是 numpy array repr，ast.literal_eval 静默解析错（单个拼接串）致假失败 15/27，正则 re.findall 修复后 27/27；③ 容器网络通但连接类 P2P 测试（故意连不可达地址）在容器语义下断言失败，F2P 全过为真相；④ HF 缓存权限问题用本地 Dataset（load_from_disk）绕过。
tags: [SWE-bench, 官方harness, OrbStack, numpy-repr, arm64]
source: {}
status: active
created_at: "2026-08-18T01:51:29.442778+08:00"
updated_at: "2026-08-18T01:51:29.442778+08:00"
---