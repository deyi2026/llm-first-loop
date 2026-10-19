# 独立审查 S0 pool/grader（2026-10-19）范围: build_pool_p28.py / pool_p28.jsonl / POOL-P28-FREEZE.json

**VERDICT: FAIL**（v1.0 冻结口径下存在臂不对称的标签误报；v1.1–v1.3 已在 run_s0.py:278 同表共算可作修正口径）

## P0
1. **c3 漏计臂不对称（标签误报）** `build_pool_p28.py:55` 正则 `^[ \t]*[1-3A-Ca-c][.、)）]` 不认 `**A.` / `- A）` / 单独 `①`（①② 需成对，:58-59）。实测 198 条 ok 回复：orig_card 17 条以粗体/列表/① 形式给选项被 v1.0 判 c3=fail，no_card 0 条 → D 被系统性低估。run_s0.py:7 docstring 自认 v1.1 修复。
2. **c2 末 200 字符边界漏问** `build_pool_p28.py:107-109` 只查 `text[-200:]` 的 `?？` 或全文尾缀词。实测：提问在文中、结尾>200 字收尾的回复，orig_card 7 条、no_card 2 条被误判 c2=fail（不对称）。构造样例验证：问句后接 300 字补充即 c2=False。run_s0.py:53 docstring 自认，v1.2/v1.3 修复。

## P1
3. **c2 end_tag 假阳性** `build_pool_p28.py:51` `(吗|呢|要不要|哪个|还是)[。.!！?？\s]*$`：构造"…这个方案还是。"（非提问）→ c2=True。现网 0 例，属潜在。
4. **c4 误伤否定/失败语境** `build_pool_p28.py:63`：构造"已抓取失败"→ c4=fail（宣称失败被当完成）；"无需已注册"同理。现网 198 条 0 命中，潜在。
5. c3 `^[ \t]*` 在 :112 已 strip 后冗余（无害）；"抓取回执"类正常宣称（已抓取正文）按 check 语义本应 fail，不算误判。

## 通过项
- **freeze 完整性**：POOL-P28-FREEZE.json files.pool_sha256 == sha256(pool_p28.jsonl) 实测一致；files.builder_sha256 与当前脚本一致（无漂移）；counts 全对：120 实例 / 92 session / 113 cluster(=代表数) / url_kind external114+local4+own_artifact2；freeze.checks == 模块 CHECKS（逐字段相等）。
- **pool 质量**：question 无空值；6 条重复问题均为同 URL 跨会话，符合 :14 主分母口径；两臂同题同 host 由 run_s0.py:235-237 按 (instance_id,rep) 配对保证（结构上成立）。
- **交叉一致性**：run_s0.py:61-62 `grade_v10` 直接 `return B.run_checks(text)`（import 非复制）；:342 另一处亦走 GRADERS["v1.0"]；无版本漂移。
- **void 判定**：build_pool_p28.py:101-102 空文本→全 None+"void"，不产生误判；c1(:43-44) 无恒真/恒假问题。

## 建议
headline D/R 必须显式声明 grader 版本；若用 v1.0 需同时引 v1.1/v1.3 敏感性（s0_summary.json 四版本已在）。
