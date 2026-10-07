---
method_id: attribute-masked-test-failure-via-inner-exception-type-15b70f722c9c
name: attribute-masked-test-failure-via-inner-exception-type
description: 当测试驱动器/夹层把异常吞掉转为返回值（swallow-and-return），失败报告呈现为被包装的异常对象（如 AttributeError: 'NameError' object has no attribute 'content'）时，不要为『拿更多细节』重跑 pytest -x 或另写复现脚本：内层异常的类型本身就是归因信号——NameError→测试代码内有未定义名（最常见：该用例漏了 sibling 都有的局部 import），TypeError→签名不符，KeyError→键缺失。对照同文件 sibling 用例已展示的导入惯例即可直接定位修复点。内层异常指向被测生产代码时，才切换到真 traceback/最小复现路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8098b445-b87e-4252-a938-91924f37f4db:127:633371769d3f6ba17d52
evidence_refs: learning:learn:cc9f7bf95168
created_at: 2026-10-07T11:18:07.766007+08:00
updated_at: 2026-10-07T11:18:07.766007+08:00
---
## Trigger
测试失败输出中，断言失败的实体是一个被驱动器捕获并返回的异常对象（外层 AttributeError/包装错误里嵌着内层异常类型），且该驱动器会把异常吞掉作为结果返回而非直接抛出。

## Discriminator
首次失败输出中已可见的内层异常类型（NameError=未定义名/漏局部导入），加上同一 diff/文件中 sibling 用例的可见导入惯例（各用例在函数体内局部 import；失败用例恰好缺这一行）——这些事实在第一次失败时已全部在手，足以把候选根因缩到『失败用例体内某个名字未定义』。

## Short path
- 读首次失败输出，提取内层异常类型并映射到错误类别（NameError→测试体内有未定义名）。
- 定位失败用例体内该名字的使用点，对照 sibling 用例的局部导入模式确认缺失（失败用例用了 LLMResponse 但没有 sibling 都有的局部 import）。
- 在失败用例内补上缺失导入/定义，最小改动。
- 重跑该用例与同文件套件，全绿即停；跳过重复的 traceback 重跑与复现脚本。

## Stop conditions
- 首次失败输出已含内层异常类型并能映射到修复位置时，不再执行任何重复诊断调用。
- 修复后失败用例与同文件邻近用例全部通过。
- 内层异常类型不可得，或归因指向被测生产代码而非测试代码——立即切换到完整 traceback/最小复现路径，不套用本方法。

## Verification
- 单独重跑原失败用例通过；同文件套件全绿。
- 确认修复只落在测试侧的缺失导入/定义，被测实现未被顺手改动。

## Counterexamples
- 内层异常发生在被测生产代码里（如被测模块自身 NameError/TypeError）——此时 swallowed 信息不足，需要完整 traceback 或最小复现，不能只改测试导入。
- 失败是普通 assert 不匹配、无包裹异常对象——走常规断言诊断，不适用内层类型归因。
- harness 不吞异常、traceback 完整可见——直接读 traceback 即可，本规则无增益。
- 同文件没有可对照的导入惯例（全新测试文件）——应在写入前先看文件头 import 区确立惯例，而非事后归因。
