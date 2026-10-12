# ANCHOR 裁决（一次性，2026-10-05T23:41:09+08:00）

- verdict：**HOLD**
- G1 主门槛：operator×R1 = 9/12（门 ≥10）→ FAIL
- G2 A 格子门：6/6（门 ≥5/6）→ PASS
- prereg sha256：60c4252b121313091cc88fe65a58a46d757c02ebbbf07981c5b8d37a7986c4fa

| case | 格 | operator | R1 | 一致 |
|---|---|---|---|---|
| iq-B10 | B | APPLY | SKIP | ✗ |
| iq-D01 | D | APPLY | SKIP | ✗ |
| iq-D02 | D | APPLY | SKIP | ✗ |
| iq-A04 | A | APPLY | APPLY | ✓ |
| iq-C01 | C | APPLY | APPLY | ✓ |
| iq-B19 | B | APPLY | APPLY | ✓ |
| iq-A03 | A | APPLY | APPLY | ✓ |
| iq-C08 | C | APPLY | APPLY | ✓ |
| iq-A05 | A | APPLY | APPLY | ✓ |
| iq-A01 | A | APPLY | APPLY | ✓ |
| iq-A06 | A | APPLY | APPLY | ✓ |
| iq-A02 | A | APPLY | APPLY | ✓ |

## B19 披露（PREREG §4）

- operator=APPLY，R1=APPLY，一致=True；理由：可用

> 裁决映射见 ANCHOR-PREREG §3：PASS→登记簿追加事件并升级声明；HOLD/FAIL→如实登记不升级。
