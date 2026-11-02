---
title: 推广-sed派生脚本两类无分隔符变体漏改-输出路径与内嵌JS数组须grep双检
scenario: "推广流水线每班从上一班脚本 sed 派生新脚本（research/build/publish/poll/geturl/public_verify），同文件内混杂\"带连字符/无连字符\"两种文件名前缀，且 Python 代码内嵌 JS 字符串与 Python 列表字面量格式不同。"
root_cause: ""
solution: sed 派生后必须 grep 双检：对每个改写目标分别 grep 旧串（期望 0 命中）与新串（期望命中预期行数），输出路径常量与内嵌 JS 数组单独列出检查；误覆盖的确定性产物用原脚本重跑恢复并比对 STATUS 记录的 sha256。
evidence: "docs/promotion/_d50_build.py 首轮 OUT 未改（sed 's/daily-49/daily-50/g' 不匹配 daily49）；docs/promotion/_d50_public_verify.py 首轮 figs 213-216 hit=false（JS 数组无空格未被替换）；docs/promotion/STATUS-20261101-daily50.md 第十节 d49 回执保护记录；d49 恢复验证 shasum=df82cd0f…与 STATUS-20261101-daily49.md:33 逐字一致"
tags: [推广发布, sed, 脚本派生, 回执保护, grep复核]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-01T13:42:17.034531+08:00"
updated_at: "2026-11-01T13:42:17.034531+08:00"
---

用 sed 从旧班脚本派生新班脚本（推广流水线常态）时，两类"无分隔符变体"最容易漏改且不报错：①标识符变体——同一前缀在仓库里有 daily-49（带连字符）与 daily49（无连字符）两种写法，sed 's/daily-49/daily-50/g' 不会碰后者，曾导致 d50 构建误写 receipts/daily49-paste.html（覆盖 d49 回执；因构建确定性以 _d49_build.py 重跑恢复且 sha256 与 d49 STATUS 记录逐字一致，未损失）；②JS/正则内无空格数组——Python 侧 FIGS=["213", "214",...]（逗号后有空格）与注入 JS 的 ['213','214',...]（无空格）不同构，sed 带空格模式只改前者，公网验收图注检查首轮全部 false 才暴露。防护：派生脚本后 grep 新旧两串各一遍（旧串应=0、新串应覆盖预期位置），特别是输出路径常量与内嵌 JS 字符串；对被误覆盖的历史回执，若原构建脚本与输入仍在，重跑即确定性恢复，用 STATUS 记录的 sha256 验证一致性。