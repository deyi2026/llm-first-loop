---
method_id: owning-name-key-before-mechanism-keyword-in-code-locate-4c57dddea26a
name: owning-name-key-before-mechanism-keyword-in-code-locate
description: 手持缺陷/变更单描述去定位实现代码时，描述里往往同时有两类键：属主级（点名的函数/门类/模块，如 review_admission）与机制级（通用 git/工具惯用语，如 merge-base(HEAD, main)）。首选属主级键定位：机制惯用语会被仓库里成片的 evals/harness/测试脚本逐字复述，命中噪声主导。噪声列表若含 test_X.py 命中，可直接由测试名推导实现模块。与『截断记录按 ref 水合/不再宽道重复获取』类卡互补：本卡管首次定位的选键，不管重复获取与存储定位。
aliases: grep出来全是evals脚本, 从变更单描述找实现文件, 搜代码用函数名还是关键词, 搜索词被测试脚本刷屏, 工单定位实现位置
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:2ef924ad-22aa-459c-881a-b100534b16c2:206:518d18bc74a20ca5e689
evidence_refs: learning:learn:101dd35153ab
created_at: 2026-10-29T12:52:28.886737+08:00
updated_at: 2026-10-29T12:52:28.886737+08:00
---
## Trigger
需在代码库中定位一段被描述（变更单/缺陷报告/评审意见）点名、但未直接给出路径的实现，且描述同时含属主级 token（点名函数/模块/门类/测试名）与机制级惯用语（如 merge-base、--is-ancestor 等通用工具调用语）

## Discriminator
发起搜索前已持有的描述原文中，属主级 token（如 review_admission(kind=full_test)，另一条甚至直接给出 file:line:function）与机制级 token 并存；属主级 token 预期碰撞数显著更低，而机制惯用语在含大量 eval/harness 脚本的仓库会被成片逐字复述

## Short path
- 从手持描述提取全部候选键，按属主特异性排序：精确路径/行号 > 点名函数/模块/测试文件名 > 独特字面量（错误码/marker）> 通用机制惯用语
- 用最高特异性键定向定位（如由 test_review_host_admission.py 命中推导并直读 review_host_admission.py），一次解析『实现在哪』这一未知量
- 读到候选区域后与描述机制互证（点名的函数、kind、既有分支如 push_base 与单据描述一致）即停止定位，进入实施
- 确需单据全文时按 search_records 命中返回的 stable ref 精确水合，不以机制词做全库内容搜索

## Stop conditions
- 属主文件目标区已读取且其中可见与单据描述一致的机制（函数名/分支/注释），定位未知量闭合
- 高特异性键无命中时，才降级用机制词且限定源码目录范围（排除 evals/tests/docs/data 类目录）

## Verification
- 实现位置与单据描述互相印证：点名的函数/kind/行为在所读代码中逐一对上
- 改动后目标测试与相邻回归通过，反证定位正确

## Counterexamples
- 描述只有症状、无任何属主名（如『启动即卡死』）：只能用症状/机制词且必须限域，选键排序无从生效
- 描述引用的代码行含独特字面量（自定义错误码、marker 字符串）：该字面量比属主名更选择性，应先用字面量
- 小仓库无 harness/文档饱和：merge-base 这类词一次即中，刻意选键属过度工程
