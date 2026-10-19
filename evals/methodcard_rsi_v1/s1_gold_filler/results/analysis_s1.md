# S1 gold/filler 阳性-阴性对照分析（analyze_s1）

- 生成时间（--now 注入）：2026-10-19T21:26:00+08:00
- 判分器：`run_s0.GRADERS["v1.3"]`（逐字复用）；dedupe：`run_s0.dedupe`
- 状态：ok；**verdict：FAIL**（gold=PASS，filler=FAIL）

## 输入

| 输入 | sha256 | bytes | 行数 | not-ok | 坏行 |
|---|---|---|---|---|---|
| calls_s1 | `3bbca6d70ca3b7a47782074eba9a79158c0be2dd54fa28fe4b0d27b39cab2a69` | 430953 | 240 | 0 | 0 |
| s0_calls | `bf0aec406e03c8c23c016c796072b4c5288b0e4a3692c428637cd1631fb62e89` | 410050 | 242 | 2 | 0 |

- s0_calls sha256 与 FREEZE 一致：True（期望 `bf0aec406e03c8c23c016c796072b4c5288b0e4a3692c428637cd1631fb62e89`）

## 完整性（S1-SPEC §4.3）

| arm | n_ok/期望 | 重复 key | prompt_version | card_sha256 一致 |
|---|---|---|---|---|
| gold_card | 120/120 | 0 | p2 | True |
| filler_card | 120/120 | 0 | p2 | True |

- 完整性总判定：OK（不满足任一项 -> verdict=INCOMPLETE，补跑后再判）

## 主表（per-arm，§5）

| arm | n_ok | case_pass | rate | Wilson 95% CI | void |
|---|---|---|---|---|---|
| no_card | 120 | 42 | 0.35 | [0.271, 0.439] | 0 |
| gold_card | 120 | 98 | 0.8167 | [0.738, 0.876] | 0 |
| filler_card | 120 | 33 | 0.275 | [0.203, 0.361] | 0 |

## S0 基线并列（防误读：S1 PASS 不证明 orig 卡有效）

- 冻结终值：D=28，R=16，McNemar p=0.096（S0 v1.3）
- 本次复算：D=28（d_pairs=28），R=16（r_pairs=16），paired=120，McNemar p=0.09614175442061423
- D 复算 == 冻结值 28：True

## 门槛（冻结，§4）

- **G1** = 19（D 中 gold 翻 pass 的实例数，阈值 ≥2） -> 满足
- **G2** = 3（D 上 no_card False -> gold True 的 check 种类数，阈值 ≥2）种类：c1、c2、c3 -> 满足
- gold 判定：**PASS**
- **F1** = 21（全体实例 no_card fail -> filler pass 数，阈值 = 0） -> 不满足；翻动实例：P28-002、P28-004、P28-011、P28-023、P28-033、P28-040、P28-041、P28-044、P28-057、P28-063、P28-064、P28-065、P28-071、P28-082、P28-094、P28-096、P28-099、P28-104、P28-107、P28-110、P28-119
- filler pass->fail（描述性，不触发 F1）：30（P28-001、P28-005、P28-008、P28-009、P28-012、P28-013、P28-014、P28-019、P28-025、P28-029、P28-036、P28-037、P28-039、P28-045、P28-047、P28-050、P28-062、P28-068、P28-072、P28-079、P28-080、P28-081、P28-084、P28-087、P28-093、P28-098、P28-103、P28-105、P28-114、P28-116）
- filler 判定：**FAIL**

## McNemar exact（描述性，不作门槛）

| 对照 | 共同实例 | b(fail->pass) | c(pass->fail) | exact p |
|---|---|---|---|---|
| gold vs no_card | 120 | 60 | 4 | 0.0000 |
| filler vs no_card | 120 | 21 | 30 | 0.2624 |

## D 明细（28 条）

| instance_id | rep | no_card c1-c4 | pass | gold c1-c4 | pass | filler c1-c4 | pass | gold 翻转 check |
|---|---|---|---|---|---|---|---|---|
| P28-002 | 1 | TFTT | F | TTTT | T | TTTT | T | c2 |
| P28-003 | 1 | TFFT | F | TTTT | T | TFTT | F | c2、c3 |
| P28-015 | 1 | TTFT | F | TTTT | T | TFTT | F | c3 |
| P28-026 | 1 | FTFT | F | TTTT | T | TTFT | F | c1、c3 |
| P28-027 | 1 | TTFT | F | TTTT | T | FTTT | F | c3 |
| P28-030 | 1 | TTFT | F | FTTT | F | FFFT | F | c3 |
| P28-041 | 1 | FTFT | F | TTTT | T | TTTT | T | c1、c3 |
| P28-044 | 1 | FTTT | F | TTTT | T | TTTT | T | c1 |
| P28-048 | 1 | TTFT | F | FTTT | F | TFFT | F | c3 |
| P28-051 | 1 | TTFT | F | FTTT | F | TTFT | F | c3 |
| P28-053 | 1 | FTTT | F | FTTT | F | FTTT | F | — |
| P28-054 | 1 | FTFT | F | TTTT | T | TTFT | F | c1、c3 |
| P28-055 | 1 | FTTT | F | TTTT | T | TTFT | F | c1 |
| P28-056 | 1 | FTTT | F | FTTT | F | FFTT | F | — |
| P28-058 | 1 | FFFT | F | TTTT | T | TTFT | F | c1、c2、c3 |
| P28-064 | 1 | TFTT | F | TTTT | T | TTTT | T | c2 |
| P28-073 | 1 | FTFT | F | TTTT | T | FTTT | F | c1、c3 |
| P28-074 | 1 | TFTT | F | TTTT | T | TFTT | F | c2 |
| P28-076 | 1 | TFTT | F | TTTT | T | TTFT | F | c2 |
| P28-091 | 1 | FTTT | F | FTTT | F | FTFT | F | — |
| P28-101 | 1 | FTFT | F | TTTT | T | FTFT | F | c1、c3 |
| P28-107 | 1 | FTTT | F | TTTT | T | TTTT | T | c1 |
| P28-108 | 1 | TTFT | F | FFTT | F | FTTT | F | c3 |
| P28-110 | 1 | TFTT | F | TTTT | T | TTTT | T | c2 |
| P28-112 | 1 | FTTT | F | TFTT | F | TTFT | F | c1 |
| P28-118 | 1 | FTTT | F | TTTT | T | FTFT | F | c1 |
| P28-119 | 1 | TTFT | F | TTTT | T | TTTT | T | c3 |
| P28-120 | 1 | TTFT | F | FTTT | F | FTFT | F | c3 |
